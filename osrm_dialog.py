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
from qgis.gui import QgsMapLayerProxyModel
from qgis.core import (
    QgsMessageLog, QgsCoordinateTransform,
    QgsCoordinateReferenceSystem, QgsMapLayerRegistry
    )


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
    def __init__(self, iface, parent=None):
        """Constructor."""
        super(OSRM_batch_route_Dialog, self).__init__(parent)
        self.setupUi(self)
        self.iface = iface
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

    def _set_layer_field_combo(self, layer):
        self.FieldOriginX.setLayer(layer)
        self.FieldOriginY.setLayer(layer)
        self.FieldDestinationX.setLayer(layer)
        self.FieldDestinationY.setLayer(layer)

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
