# -*- coding: utf-8 -*-
"""
/***************************************************************************
 OSRMDialog
                                 A QGIS plugin
 Find a route with OSRM
                             -------------------
        begin                : 2015-09-29
        git sha              : $Format:%H$
        copyright            : (C) 2015 by mthh
        email                : mthh@#!.org
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import os
from PyQt4 import QtGui, uic
from PyQt4.QtCore import pyqtSlot
from httplib import HTTPConnection
from qgis.gui import QgsMapLayerProxyModel
from qgis.core import (
    QgsMessageLog, QgsCoordinateTransform, QgsFeature,
    QgsCoordinateReferenceSystem, QgsMapLayerRegistry,
    QgsVectorLayer, QgsVectorFileWriter
    )
from osrm_utils import check_host, decode_geom, lru_cache
try:
    import ujson as json
except ImportError:
    import json

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'osrm_dialog_base.ui'))

FORM_CLASS_t, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'osrm_table_dialog_base.ui'))

FORM_CLASS_a, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'osrm_access_dialog_base.ui'))

FORM_CLASS_b, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'osrm_batch_route.ui'))


class OSRMDialog(QtGui.QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        """Constructor."""
        super(OSRMDialog, self).__init__(parent)
        self.setupUi(self)


class OSRM_table_Dialog(QtGui.QDialog, FORM_CLASS_t):
    def __init__(self, parent=None):
        """Constructor."""
        super(OSRM_table_Dialog, self).__init__(parent)
        self.setupUi(self)
        self.pushButton_fetch.setDisabled(True)
        self.comboBox_layer.setFilters(QgsMapLayerProxyModel.PointLayer)
        self.comboBox_layer.layerChanged.connect(
            lambda x: self.comboBox_idfield.setLayer(x)
            )
        self.lineEdit_output.textChanged.connect(
            lambda x: self.pushButton_fetch.setEnabled(True)
            if '.csv' in x else self.pushButton_fetch.setDisabled(True)
            )
        self.comboBox_layer_2.setFilters(QgsMapLayerProxyModel.PointLayer)
        self.comboBox_layer_2.layerChanged.connect(
            lambda x: self.comboBox_idfield_2.setLayer(x)
            )

class OSRM_access_Dialog(QtGui.QDialog, FORM_CLASS_a):
    def __init__(self, parent=None):
        """Constructor."""
        super(OSRM_access_Dialog, self).__init__(parent)
        self.setupUi(self)
        self.pushButtonClear.clicked.connect(self.clear_all_isochrone)
        self.nb_isocr = 0

    def clear_all_isochrone(self):
        self.lineEdit_xyO.setText('')
        self.nb_isocr = 0
        for layer in QgsMapLayerRegistry.instance().mapLayers():
            if 'isochrone_osrm' in layer:
                QgsMapLayerRegistry.instance().removeMapLayer(layer)


class OSRM_batch_route_Dialog(QtGui.QDialog, FORM_CLASS_b):
    def __init__(self, iface, http_headers, parent=None):
        """Constructor."""
        super(OSRM_batch_route_Dialog, self).__init__(parent)
        self.setupUi(self)
        self.iface = iface
        self.http_headers = http_headers
        self.ComboBoxOrigin.setFilters(QgsMapLayerProxyModel.PointLayer)
        self.ComboBoxDestination.setFilters(QgsMapLayerProxyModel.PointLayer)
        self.ComboBoxCsv.setFilters(QgsMapLayerProxyModel.NoGeometry)
        self.pushButtonReverse.clicked.connect(self.reverse_OD_batch)
        self.check_two_layers.stateChanged.connect(
            lambda st: self.check_csv.setCheckState(0) if (
                st == 2 and self.check_csv.isChecked()) else None)
        self.check_csv.stateChanged.connect(
            lambda st: self.check_two_layers.setCheckState(0) if (
                st == 2 and self.check_two_layers.isChecked()) else None)
        self.ComboBoxCsv.layerChanged.connect(self._set_layer_field_combo)
        self.nb_done = 0

    def _set_layer_field_combo(self, layer):
        self.FieldOriginX.setLayer(layer)
        self.FieldOriginY.setLayer(layer)
        self.FieldDestinationX.setLayer(layer)
        self.FieldDestinationY.setLayer(layer)

    @lru_cache(maxsize=25)
    def query_url(self, url, host):
        self.conn.request('GET', url, headers=self.http_headers)
        parsed = json.loads(self.conn.getresponse().read().decode('utf-8'))
        return parsed

    def _prepare_queries(self):
        """Get the coordinates for each viaroute to query"""
        if self.check_two_layers.isChecked():
            origin_layer = self.ComboBoxOrigin.currentLayer()
            destination_layer = self.ComboBoxDestination.currentLayer()
            if '4326' not in origin_layer.crs().authid():
                xform = QgsCoordinateTransform(
                    origin_layer.crs(), QgsCoordinateReferenceSystem(4326))
                origin_ids_coords = \
                    [(ft.id(), xform.transform(ft.geometry().asPoint()))
                     for ft in origin_layer.getFeatures()]
            else:
                origin_ids_coords = \
                    [(ft.id(), ft.geometry().asPoint())
                     for ft in origin_layer.getFeatures()]

            if '4326' not in destination_layer.crs().authid():
                xform = QgsCoordinateTransform(
                    origin_layer.crs(), QgsCoordinateReferenceSystem(4326))
                destination_ids_coords = \
                    [(ft.id(), xform.transform(ft.geometry().asPoint()))
                     for ft in destination_layer.getFeatures()]
            else:
                destination_ids_coords = \
                    [(ft.id(), ft.geometry().asPoint())
                     for ft in destination_layer.getFeatures()]

            if len(origin_ids_coords) * len(destination_ids_coords) > 100000:
                QtGui.QMessageBox.information(
                    self.iface.mainWindow(), 'Info',
                    "Too many route to calculate, try with less than 100000")
                return -1

            return [(origin[1][1], origin[1][0], dest[1][1], dest[1][0])
                    for origin in origin_ids_coords
                    for dest in destination_ids_coords]

        elif self.check_csv.isChecked():
            layer = self.ComboBoxCsv.currentLayer()
            xo_col = self.FieldOriginX.currentField()
            yo_col = self.FieldOriginY.currentField()
            xd_col = self.FieldDestinationX.currentField()
            yd_col = self.FieldDestinationY.currentField()
            return [(str(ft.attribute(yo_col)), str(ft.attribute(xo_col)),
                     str(ft.attribute(yd_col)), str(ft.attribute(xd_col)))
                    for ft in layer.getFeatures()]
        else:
            QtGui.QMessageBox.information(
                self.iface.mainWindow(), 'Error',
                "Choose a method between points layers / csv file")
            return -1

    def reverse_OD_batch(self):
        if self.check_csv.isChecked():
            self.switch_OD_fields()
        elif self.check_two_layers.isChecked():
            self.swtich_OD_box()
        else:
            self.switch_OD_fields()
            self.swtich_OD_box()

    def switch_OD_fields(self):
        try:
            oxf = self.FieldOriginX.currentField()
            self.FieldOriginX.setField(
                self.FieldDestinationX.currentField())
            oyf = self.FieldOriginY.currentField()
            self.FieldOriginY.setField(
                self.FieldDestinationY.currentField())
            self.FieldDestinationX.setField(oxf)
            self.FieldDestinationY.setField(oyf)
        except Exception as err:
            QgsMessageLog.logMessage(
                'OSRM-plugin error report :\n {}'.format(err),
                level=QgsMessageLog.WARNING)

    def swtich_OD_box(self):
        try:
            tmp_o = self.ComboBoxOrigin.currentLayer()
            tmp_d = self.ComboBoxDestination.currentLayer()
            self.ComboBoxOrigin.setLayer(tmp_d)
            self.ComboBoxDestination.setLayer(tmp_o)
        except Exception as err:
            QgsMessageLog.logMessage(
                'OSRM-plugin error report :\n {}'.format(err),
                level=QgsMessageLog.WARNING)

    @pyqtSlot()
    def get_batch_route(self):
        """Query the API and make a line for each route"""
        self.filename = self.lineEdit_output.text()
        if not self.check_add_layer.isChecked() \
                and '.shp' not in self.filename:
            QtGui.QMessageBox.information(
                self.iface.mainWindow(), 'Error',
                "Output have to be saved and/or added to the canvas")
            return -1
        try:
            self.host = check_host(self.lineEdit_host.text())
        except ValueError:
            self.iface.messageBar().pushMessage(
                "Error", "Please provide a valid non-empty URL", duration=10)
        self.nb_route, errors, consec_errors = 0, 0, 0
        queries = self._prepare_queries()
        try:
            nb_queries = len(queries)
        except TypeError:
            return -1
        if nb_queries < 1:
            QtGui.QMessageBox.information(
                self.iface.mainWindow(), 'Info',
                "Something wrong append - No locations to request"
                .format(self.filename))
            return -1
        elif nb_queries > 500 and 'project-osrm' in self.host:
            QtGui.QMessageBox.information(
                self.iface.mainWindow(), 'Error',
                "Please, don't make heavy requests on the public API")
            return -1
        self.conn = HTTPConnection(self.host)
        features = []
        for yo, xo, yd, xd in queries:
            try:
                url = (
                    "/viaroute?loc={},{}&loc={},{}"
                    "&instructions=false&alt=false").format(yo, xo, yd, xd)
                parsed = self.query_url(url, self.host)
            except Exception as err:
                self._display_error(err, 1)
                errors += 1
                consec_errors += 1
                continue
#            else:
            try:
                line_geom = decode_geom(parsed['route_geometry'])
            except KeyError:
                self.iface.messageBar().pushMessage(
                    "Error",
                    "No route found between {} and {}"
                    .format((xo, yo), (xd, yd)),
                    duration=5)
                errors += 1
                consec_errors += 1
                continue
#                else:
            fet = QgsFeature()
            fet.setGeometry(line_geom)
            fet.setAttributes([
                self.nb_route,
                parsed['route_summary']['total_time'],
                parsed['route_summary']['total_distance']
                ])
            features.append(fet)
            consec_errors = 0
            self.nb_route += 1
            if consec_errors > 50:
                self.conn.close()
                self._display_error("Too many errors occured when trying to "
                                    "contact the OSRM instance - Route calcula"
                                    "tion has been stopped ", 2)
                break
        self.conn.close()
        self.nb_done += 1

        if len(features) < 1:
            QtGui.QMessageBox.information(
                self.iface.mainWindow(), 'Info',
                "Something wrong append - No feature fetched"
                .format(self.filename))
            return -1
        else:
            self.return_batch_route(features)

    @pyqtSlot()
    def return_batch_route(self, features):
        """Save and/or display the routes retrieved"""
        osrm_batch_route_layer = QgsVectorLayer(
            "Linestring?crs=epsg:4326&field=id:integer"
            "&field=total_time:integer(20)&field=distance:integer(20)",
            "routes_osrm{}".format(self.nb_done), "memory")
        provider = osrm_batch_route_layer.dataProvider()
        provider.addFeatures(features)
        QgsMapLayerRegistry.instance().addMapLayer(osrm_batch_route_layer)
        if self.filename:
            error = QgsVectorFileWriter.writeAsVectorFormat(
                osrm_batch_route_layer, self.filename,
                self.encoding, None, "ESRI Shapefile")
            if error != QgsVectorFileWriter.NoError:
                self.iface.messageBar().pushMessage(
                    "Error",
                    "Can't save the result into {} - Output have been "
                    "added to the canvas (see QGis log for error trace"
                    "back)".format(self.filename), duration=10)
                QgsMessageLog.logMessage(
                    'OSRM-plugin error report :\n {}'.format(error),
                    level=QgsMessageLog.WARNING)
                self.iface.setActiveLayer(osrm_batch_route_layer)
                return -1
            else:
                QtGui.QMessageBox.information(
                    self.iface.mainWindow(), 'Info',
                    "Result saved in {}".format(self.filename))
        if self.check_add_layer.isChecked():
            self.iface.setActiveLayer(osrm_batch_route_layer)
        else:
            QgsMapLayerRegistry.instance().removeMapLayer(
                osrm_batch_route_layer.id())
        self.iface.messageBar().clearWidgets()