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
import csv
import numpy as np
from PyQt4 import QtGui, uic
from PyQt4.QtCore import pyqtSlot, Qt
from re import match
from sys import version_info
from httplib import HTTPConnection
from codecs import open as codecs_open
from qgis.gui import QgsMapLayerProxyModel, QgsMapToolEmitPoint
from qgis.core import (
    QgsMessageLog, QgsCoordinateTransform, QgsFeature,
    QgsCoordinateReferenceSystem, QgsMapLayerRegistry,
    QgsVectorLayer, QgsVectorFileWriter, QgsPoint,
    QgsGeometry, QgsRuleBasedRendererV2, QgsSymbolV2, QGis,
    QgsGraduatedSymbolRendererV2, QgsRendererRangeV2, QgsFillSymbolV2,
    QgsSingleSymbolRendererV2
    )
from osrm_utils import *
import json


FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'osrm_dialog_base.ui'))

FORM_CLASS_t, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'osrm_table_dialog_base.ui'))

FORM_CLASS_a, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'osrm_access_dialog_base.ui'))

FORM_CLASS_b, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'osrm_batch_route.ui'))

FORM_CLASS_tsp, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'osrm_dialog_tsp.ui'))

HTTP_HEADERS = {
    'connection': 'keep-alive',
    'User-Agent': ' '.join(
        ['QGIS-desktop', QGis.QGIS_VERSION, '/',
         'Python-httplib', str(version_info[:3])[1:-1].replace(', ', '.')])
    }


class TemplateOsrm(object):
    def display_error(self, error, code):
        msg = {
            1: "An error occured when trying to contact the OSRM instance",
            2: "OSRM plugin error report : Too many errors occured "
               "when trying to contact the OSRM instance at {} - "
               "Route calculation has been stopped".format(self.host),
            }
        self.iface.messageBar().pushMessage(
            "Error", msg[code] + "(see QGis log for error traceback)",
            duration=10)
        QgsMessageLog.logMessage(
            'OSRM-plugin error report :\n {}'.format(error),
            level=QgsMessageLog.WARNING)

    @lru_cache(maxsize=25)
    def query_url(self, url, host):
        self.conn.request('GET', url, headers=self.http_headers)
        parsed = json.loads(self.conn.getresponse().read().decode('utf-8'))
        return parsed

    def store_origin(self, point):
        if '4326' not in self.canvas.mapSettings().destinationCrs().authid():
            crsSrc = self.canvas.mapSettings().destinationCrs()
            xform = QgsCoordinateTransform(
                crsSrc, QgsCoordinateReferenceSystem(4326))
            point = xform.transform(point)
        self.origin = point
        self.canvas.unsetMapTool(self.originEmit)
        self.lineEdit_xyO.setText(str(point))

class OSRM_DialogTSP(QtGui.QDialog, FORM_CLASS_tsp, TemplateOsrm):
    def __init__(self, iface, parent=None):
        super(OSRM_DialogTSP, self).__init__(parent)
        self.setupUi(self)
        self.iface = iface
        self.http_headers = HTTP_HEADERS
        self.pushButton_display.clicked.connect(self.run_tsp)
        self.pushButton_clear.clicked.connect(self.clear_results)
        self.nb_route = 0

    def clear_results(self):
        for layer in QgsMapLayerRegistry.instance().mapLayers():
            if 'tsp_solution_osrm' in layer:
                QgsMapLayerRegistry.instance().removeMapLayer(layer)
        self.nb_route = 0

    def run_tsp(self):
        layer = self.comboBox_layer.currentLayer()
        if self.checkBox_selec_features.isChecked():
            pass
        coords, _ = get_coords_ids(layer, '')
        if len(coords) < 2:
            return -1

        try:
            self.host = check_host(self.lineEdit_host.text())
        except ValueError:
            self.iface.messageBar().pushMessage(
                "Error", "Please provide a valid non-empty URL", duration=10)
        _ = coords.pop(0)
        query = ''.join(
            ['/trip?loc={},{}&loc='.format(_[1], _[0]),
             '&loc='.join(['{},{}'.format(i[1], i[0]) for i in coords])])
        try:
            self.conn = HTTPConnection(self.host)
            self.parsed = self.query_url(query, self.host)
            self.conn.close()
        except Exception as err:
            self.iface.messageBar().pushMessage(
                "Error", "An error occured when trying to contact the OSRM "
                "instance (see QGis log for error traceback)",
                duration=10)
            QgsMessageLog.logMessage(
                'OSRM-plugin error report :\n {}'.format(err),
                level=QgsMessageLog.WARNING)
            return

        try:
            line_geoms = \
                [decode_geom(self.parsed['trips'][i]['route_geometry'])
                for i in range(len(self.parsed['trips']))]
        except KeyError:
            self.iface.messageBar().pushMessage(
                "Error",
                "?...",
                duration=5)
            return

        tsp_route_layer = QgsVectorLayer(
            "Linestring?crs=epsg:4326&field=id:integer"
            "&field=total_time:integer(20)&field=distance:integer(20)",
            "tsp_solution_osrm{}".format(self.nb_route), "memory")
        my_symb = prepare_route_symbol(self.nb_route)
        tsp_route_layer.setRendererV2(QgsSingleSymbolRendererV2(my_symb))
        features = []
        for idx, feature in enumerate(self.parsed['trips']):
            ft = QgsFeature()
            ft.setGeometry(line_geoms[idx])
            ft.setAttributes([idx, 
                              feature['route_summary']['total_distance'],
                              feature['route_summary']['total_time']])
            features.append(ft)
        tsp_route_layer.dataProvider().addFeatures(features)
        tsp_route_layer.updateExtents()
        QgsMapLayerRegistry.instance().addMapLayer(tsp_route_layer)
        self.iface.setActiveLayer(tsp_route_layer)
        self.iface.zoomToActiveLayer()
        self.nb_route += 1

        if self.checkBox_instructions.isChecked():
            pass
#            pr_instruct, instruct_layer = self.prep_instruction()
#            QgsMapLayerRegistry.instance().addMapLayer(instruct_layer)
#            self.iface.setActiveLayer(instruct_layer)

class OSRMDialog(QtGui.QDialog, FORM_CLASS, TemplateOsrm):
    def __init__(self, iface, parent=None):
        """Constructor."""
        super(OSRMDialog, self).__init__(parent)
        self.setupUi(self)
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.originEmit = QgsMapToolEmitPoint(self.canvas)
        self.intermediateEmit = QgsMapToolEmitPoint(self.canvas)
        self.destinationEmit = QgsMapToolEmitPoint(self.canvas)
        self.nb_route = 0
        self.intermediate = []
        self.http_headers = HTTP_HEADERS
        self.pushButtonTryIt.clicked.connect(self.get_route)
        self.pushButtonReverse.clicked.connect(self.reverse_OD)
        self.pushButtonClear.clicked.connect(self.clear_all_single)

    def store_intermediate(self, point):
        if '4326' not in self.canvas.mapSettings().destinationCrs().authid():
            crsSrc = self.canvas.mapSettings().destinationCrs()
            xform = QgsCoordinateTransform(
                crsSrc, QgsCoordinateReferenceSystem(4326))
            point = xform.transform(point)
        self.intermediate.append(tuple(map(lambda x: round(x, 6), point)))
        self.canvas.unsetMapTool(self.intermediateEmit)
        self.lineEdit_xyI.setText(str(self.intermediate)[1:-1])

    def store_destination(self, point):
        if '4326' not in self.canvas.mapSettings().destinationCrs().authid():
            crsSrc = self.canvas.mapSettings().destinationCrs()
            xform = QgsCoordinateTransform(
                crsSrc, QgsCoordinateReferenceSystem(4326))
            point = xform.transform(point)
        self.destination = point
        self.canvas.unsetMapTool(self.destinationEmit)
        self.lineEdit_xyD.setText(str(point))

    def get_alternatives(self, provider):
        for i, alt_geom in enumerate(self.parsed['alternative_geometries']):
            decoded_alt_line = decode_geom(alt_geom)
            fet = QgsFeature()
            fet.setGeometry(decoded_alt_line)
            fet.setAttributes([
                i + 1,
                self.parsed['alternative_summaries'][i]['total_time'],
                self.parsed['alternative_summaries'][i]['total_distance']
                ])
            provider.addFeatures([fet])

    def reverse_OD(self):
        try:
            tmp = self.lineEdit_xyO.text()
            tmp1 = self.lineEdit_xyD.text()
            self.lineEdit_xyD.setText(str(tmp))
            self.lineEdit_xyO.setText(str(tmp1))
        except Exception as err:
            print(err)

    def clear_all_single(self):
        self.lineEdit_xyO.setText('')
        self.lineEdit_xyD.setText('')
        self.lineEdit_xyI.setText('')
        self.intermediate = []
        for layer in QgsMapLayerRegistry.instance().mapLayers():
            if 'route_osrm' in layer \
                    or 'instruction_osrm' in layer \
                    or 'markers_osrm' in layer:
                QgsMapLayerRegistry.instance().removeMapLayer(layer)
        self.nb_route = 0

    def prep_instruction(self, alt=None, provider=None,
                         osrm_instruction_layer=None):
        if not alt:
            osrm_instruction_layer = QgsVectorLayer(
                "Point?crs=epsg:4326&field=id:integer&field=alt:integer"
                "&field=directions:integer(20)&field=street_name:string(254)"
                "&field=length:integer(20)&field=position:integer(20)"
                "&field=time:integer(20)&field=length:string(80)"
                "&field=direction:string(20)&field=azimuth:float(10,4)",
                "instruction_osrm{}".format(self.nb_route),
                "memory")
            liste_coords = decode_geom_to_pts(self.parsed['route_geometry'])
            pts_instruct = pts_ref(self.parsed['route_instructions'])
            instruct = self.parsed['route_instructions']
            provider = osrm_instruction_layer.dataProvider()
        else:
            liste_coords = decode_geom_to_pts(
                self.parsed['alternative_geometries'][alt - 1])
            pts_instruct = pts_ref(
                self.parsed['alternative_instructions'][alt - 1])
            instruct = self.parsed['alternative_instructions'][alt - 1]

        for nbi, pt in enumerate(pts_instruct):
            fet = QgsFeature()
            fet.setGeometry(
                QgsGeometry.fromPoint(
                    QgsPoint(liste_coords[pt][0], liste_coords[pt][1])))
            fet.setAttributes([nbi, alt, instruct[nbi][0],
                               instruct[nbi][1], instruct[nbi][2],
                               instruct[nbi][3], instruct[nbi][4],
                               instruct[nbi][5], instruct[nbi][6],
                               instruct[nbi][7]])
            provider.addFeatures([fet])
        return provider, osrm_instruction_layer

    @staticmethod
    def make_OD_markers(nb, xo, yo, xd, yd, list_coords=None):
        OD_layer = QgsVectorLayer(
            "Point?crs=epsg:4326&field=id_route:integer&field=role:string(80)",
            "markers_osrm{}".format(nb), "memory")
        features = []
        fet = QgsFeature()
        fet.setGeometry(QgsGeometry.fromPoint(QgsPoint(float(xo), float(yo))))
        fet.setAttributes([nb, 'Origin'])
        features.append(fet)
        fet = QgsFeature()
        fet.setGeometry(QgsGeometry.fromPoint(QgsPoint(float(xd), float(yd))))
        fet.setAttributes([nb, 'Destination'])
        features.append(fet)
        marker_rules = [
            ('Origin', '"role" LIKE \'Origin\'', '#50b56d', 4),
            ('Destination', '"role" LIKE \'Destination\'', '#d31115', 4),
        ]
        if list_coords:
            for i, pt in enumerate(list_coords):
                fet = QgsFeature()
                fet.setGeometry(
                    QgsGeometry.fromPoint(QgsPoint(float(pt[0]), float(pt[1]))))
                fet.setAttributes([nb, 'Via point n°{}'.format(i)])
                features.append(fet)
            marker_rules.insert(
                1, ('Intermediate', '"role" LIKE \'Via point%\'', 'grey', 2))
        OD_layer.dataProvider().addFeatures(features)

        symbol = QgsSymbolV2.defaultSymbol(OD_layer.geometryType())
        renderer = QgsRuleBasedRendererV2(symbol)
        root_rule = renderer.rootRule()
        for label, expression, color_name, size in marker_rules:
            rule = root_rule.children()[0].clone()
            rule.setLabel(label)
            rule.setFilterExpression(expression)
            rule.symbol().setColor(QtGui.QColor(color_name))
            rule.symbol().setSize(size)
            root_rule.appendChild(rule)

        root_rule.removeChildAt(0)
        OD_layer.setRendererV2(renderer)
        return OD_layer

    @pyqtSlot()
    def get_route(self):
        try:
            self.host = check_host(self.lineEdit_host.text())
        except ValueError:
            self.iface.messageBar().pushMessage(
                "Error", "Please provide a valid non-empty URL", duration=10)

        origin = self.lineEdit_xyO.text()
        interm = self.lineEdit_xyI.text()
        destination = self.lineEdit_xyD.text()

        try:
            assert match('^[^a-zA-Z]+$', origin) \
                and 46 > len(origin) > 4
            assert match('^[^a-zA-Z]+$', destination) \
                and 46 > len(destination) > 4
            xo, yo = eval(origin)
            xd, yd = eval(destination)
        except:
            self.iface.messageBar().pushMessage(
                "Error", "Invalid coordinates !", duration=10)
            return -1

        if interm:
            try:
                assert match('^[^a-zA-Z]+$', interm) \
                    and 150 > len(interm) > 4
                interm = eval(''.join(['[', interm, ']']))
                tmp = ''.join(
                    ['&loc={},{}'.format(yi, xi) for xi, yi in interm])
                url = ''.join([
                    "/viaroute?loc={},{}".format(yo, xo),
                    tmp,
                    "&loc={},{}".format(yd, xd),
                    "&instructions={}&alt={}".format(
                        str(self.checkBox_instruction.isChecked()).lower(),
                        str(self.checkBox_alternative.isChecked()).lower())
                    ])
            except:
                self.iface.messageBar().pushMessage(
                    "Error", "Invalid intemediates coordinates", duration=10)

        else:
            url = ''.join([
                "/viaroute?loc={},{}&loc={},{}".format(yo, xo, yd, xd),
                "&instructions={}&alt={}".format(
                    str(self.checkBox_instruction.isChecked()).lower(),
                    str(self.checkBox_alternative.isChecked()).lower())
                ])

        try:
            self.conn = HTTPConnection(self.host)
            self.parsed = self.query_url(url, self.host)
            self.conn.close()
        except Exception as err:
            self.display_error(err, 1)
            return

        try:
            line_geom = decode_geom(self.parsed['route_geometry'])
        except KeyError:
            self.iface.messageBar().pushMessage(
                "Error",
                "No route found between {} and {}".format(origin, destination),
                duration=5)
            return

        self.nb_route += 1
        osrm_route_layer = QgsVectorLayer(
            "Linestring?crs=epsg:4326&field=id:integer"
            "&field=total_time:integer(20)&field=distance:integer(20)",
            "route_osrm{}".format(self.nb_route), "memory")
        my_symb = prepare_route_symbol(self.nb_route)
        osrm_route_layer.setRendererV2(QgsSingleSymbolRendererV2(my_symb))
        QgsMapLayerRegistry.instance().addMapLayer(osrm_route_layer)
        provider = osrm_route_layer.dataProvider()
        fet = QgsFeature()
        fet.setGeometry(line_geom)
        fet.setAttributes([0, self.parsed['route_summary']['total_time'],
                           self.parsed['route_summary']['total_distance']])
        provider.addFeatures([fet])

        OD_layer = self.make_OD_markers(self.nb_route, xo, yo, xd, yd, interm)
        QgsMapLayerRegistry.instance().addMapLayer(OD_layer)
        self.iface.setActiveLayer(OD_layer)
        osrm_route_layer.updateExtents()
        self.iface.setActiveLayer(osrm_route_layer)
        self.iface.zoomToActiveLayer()

        if self.checkBox_instruction.isChecked():
            pr_instruct, instruct_layer = self.prep_instruction()
            QgsMapLayerRegistry.instance().addMapLayer(instruct_layer)
            self.iface.setActiveLayer(instruct_layer)

        if self.checkBox_alternative.isChecked() \
                and 'alternative_geometries' in self.parsed:
            self.nb_alternative = len(self.parsed['alternative_geometries'])
            self.get_alternatives(provider)
            if self.dlg.checkBox_instruction.isChecked():
                for i in range(self.nb_alternative):
                    pr_instruct, instruct_layer = \
                       self.prep_instruction(i + 1, pr_instruct, instruct_layer)
        return


class OSRM_table_Dialog(QtGui.QDialog, FORM_CLASS_t, TemplateOsrm):
    def __init__(self, iface, parent=None):
        """Constructor."""
        super(OSRM_table_Dialog, self).__init__(parent)
        self.setupUi(self)
        self.iface = iface
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
        self.pushButton_browse.clicked.connect(self.output_dialog)
        self.pushButton_fetch.clicked.connect(self.get_table)
        self.http_headers = HTTP_HEADERS

    def output_dialog(self):
        self.lineEdit_output.clear()
        self.filename, self.encoding = save_dialog()
        if self.filename is None:
            return
        self.lineEdit_output.setText(self.filename)

    @pyqtSlot()
    def get_table(self):
        try:
            self.host = check_host(self.lineEdit_host.text())
        except ValueError:
            self.iface.messageBar().pushMessage(
                "Error", "Please provide a valid non-empty URL", duration=10)
        osrm_table_version = return_osrm_table_version(
            self.host, (1.0, 1.0), self.http_headers)
        self.filename = self.lineEdit_output.text()
        s_layer = self.comboBox_layer.currentLayer()
        d_layer = self.comboBox_layer_2.currentLayer()
        if 'old' in osrm_table_version and d_layer and d_layer != s_layer:
            QtGui.QMessageBox.information(
                self.iface.mainWindow(), 'Error',
                "Rectangular matrix aren't supported in your running version "
                "of OSRM\nPlease only select a source point layer which will "
                "be used to compute a square matrix\n(or update your OSRM "
                "instance")
            self.comboBox_layer_2.setCurrentIndex(-1)
            return -1

        elif d_layer == s_layer:
            d_layer = None

        coords_src, ids_src = \
            get_coords_ids(s_layer, self.comboBox_idfield.currentField())

        if d_layer: ### En faire une fonction :
            coords_dest, ids_dest = \
                get_coords_ids(d_layer, self.comboBox_idfield_2.currentField())

        try:
            conn = HTTPConnection(self.host)
            if d_layer:
                table, new_src_coords, new_dest_coords = \
                    rectangular_light_table(
                        coords_src, coords_dest, conn, self.http_headers)
            else:
                table = h_light_table(
                    coords_src, conn, headers=self.http_headers)
                if len(table) < len(coords_src):
                    self.iface.messageBar().pushMessage(
                        'The array returned by OSRM is smaller to the size of '
                        'the array requested\nOSRM parameter --max-table-size '
                        'should be increased', duration=20)
            conn.close()

        except ValueError as err:
            self.display_error(err, 1)
            return
        except Exception as er:
            self.display_error(er, 1)
            return

        # Convert the matrix in minutes if needed :
        if self.checkBox_minutes.isChecked():
            table = np.array(table, dtype='float64')
            table = (table / 600.0).round(1)

        # Replace the value for not found connections :
#        # With a "Not found" message, nicer output but higher memory usage :
#        if self.dlg.checkBox_empty_val.isChecked():
#            table = table.astype(str)
#            if self.dlg.checkBox_minutes.isChecked():
#                table[table == '3579139.4'] = 'Not found connection'
#            else:
#                table[table == '2147483647'] = 'Not found connection'
        # Or without converting the array to string
        # (choosed solution at this time)
        if self.checkBox_empty_val.isChecked():
            if self.checkBox_minutes.isChecked():
                table[table == 3579139.4] = np.NaN
            else:
                table[table == 2147483647] = np.NaN

        try:
            out_file = codecs_open(self.filename, 'w', encoding=self.encoding)
            writer = csv.writer(out_file, lineterminator='\n')
            if self.checkBox_flatten.isChecked():
                table = table.ravel()
                if d_layer:
                    idsx = [(i, j) for i in ids_src for j in ids_dest]
                else:
                    idsx = [(i, j) for i in ids_src for j in ids_src]
                writer.writerow([u'Origin', u'Destination', u'Time'])
                writer.writerows([
                    [idsx[i][0], idsx[i][1], table[i]]
                    for i in xrange(len(idsx))
                    ])
            else:
                if d_layer:
                    writer.writerow([u''] + ids_dest)
                    writer.writerows(
                        [[ids_src[_id]] + line
                         for _id, line in enumerate(table.tolist())])
                else:
                    writer.writerow([u''] + ids_src)
                    writer.writerows(
                        [[ids_src[_id]] + line
                         for _id, line in enumerate(table.tolist())])
            out_file.close()
            QtGui.QMessageBox.information(
                self.iface.mainWindow(), 'Done',
                "OSRM table saved in {}".format(self.filename))
        except Exception as err:
            QtGui.QMessageBox.information(
                self.iface.mainWindow(), 'Error',
                "Something went wrong...")
            QgsMessageLog.logMessage(
                'OSRM-plugin error report :\n {}'.format(err),
                level=QgsMessageLog.WARNING)


class OSRM_access_Dialog(QtGui.QDialog, FORM_CLASS_a, TemplateOsrm):
    def __init__(self, iface, parent=None):
        """Constructor."""
        super(OSRM_access_Dialog, self).__init__(parent)
        self.setupUi(self)
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.originEmit = QgsMapToolEmitPoint(self.canvas)
        self.intermediateEmit = QgsMapToolEmitPoint(self.canvas)
        self.pushButton_fetch.clicked.connect(self.get_access_isochrones)
        self.pushButtonClear.clicked.connect(self.clear_all_isochrone)
        self.nb_isocr = 0
        self.host = None
        self.progress = None
        self.max_points = 7420
        self.http_headers = HTTP_HEADERS

    def clear_all_isochrone(self):
        self.lineEdit_xyO.setText('')
        self.nb_isocr = 0
        for layer in QgsMapLayerRegistry.instance().mapLayers():
            if 'isochrone_osrm' in layer:
                QgsMapLayerRegistry.instance().removeMapLayer(layer)

    def make_prog_bar(self):
        progMessageBar = self.iface.messageBar().createMessage(
            "Creation in progress...")
        self.progress = QtGui.QProgressBar()
        self.progress.setMaximum(10)
        self.progress.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        progMessageBar.layout().addWidget(self.progress)
        self.iface.messageBar().pushWidget(
            progMessageBar, self.iface.messageBar().INFO)

    def store_intermediate_acces(self, point):
        if '4326' not in self.canvas.mapSettings().destinationCrs().authid():
            crsSrc = self.canvas.mapSettings().destinationCrs()
            xform = QgsCoordinateTransform(
                crsSrc, QgsCoordinateReferenceSystem(4326))
            point = xform.transform(point)
        tmp = self.lineEdit_xyO.text()
        self.lineEdit_xyO.setText(', '.join([tmp, repr(point)]))

    @pyqtSlot()
    def get_access_isochrones(self):
        """
        Making the accessibility isochrones in few steps:
        - make a grid of points aroung the origin point,
        - snap each point (using OSRM locate function) on the road network,
        - get the time-distance between the origin point and each of these pts
            (using OSRM table function),
        - make an interpolation grid to extract polygons corresponding to the
            desired time intervals (using matplotlib library),
        - render the polygon.
        """
        try:
            self.host = check_host(self.lineEdit_host.text())
        except ValueError:
            self.iface.messageBar().pushMessage(
                "Error", "Please provide a valid non-empty URL", duration=10)

        pts = self.lineEdit_xyO.text()

        try:
            assert match('^[^a-zA-Z]+$', pts) and len(pts) > 4
            pts = eval(pts)
        except:
            self.iface.messageBar().pushMessage("Error", "Invalid coordinates!",
                                                duration=10)
            return -1

        max_time = self.spinBox_max.value()
        inter_time = self.spinBox_intervall.value()
        self.make_prog_bar()
        version = \
            return_osrm_table_version(self.host, (1.0, 2.2), self.http_headers)
        if 'old' in version:
            polygons, levels = self.prep_accessibility_old_osrm(
                pts, self.host, inter_time, max_time)
        elif 'new' in version:
            polygons, levels = self.prep_accessibility_new_osrm(
                pts, self.host, inter_time, max_time)
        else:
            return -1

        isochrone_layer = QgsVectorLayer(
            "MultiPolygon?crs=epsg:4326&field=id:integer"
            "&field=min:integer(10)"
            "&field=max:integer(10)",
            "isochrone_osrm_{}".format(self.nb_isocr), "memory")
        data_provider = isochrone_layer.dataProvider()

        features = []
        self.progress.setValue(8.5)
        for i, poly in enumerate(polygons):
            ft = QgsFeature()
            ft.setGeometry(poly)
            ft.setAttributes([i, levels[i] - inter_time, levels[i]])
            features.append(ft)
        data_provider.addFeatures(features[::-1])
        self.nb_isocr += 1
        self.progress.setValue(9.5)
        cats = [
            ('{} - {} min'.format(levels[i]-inter_time, levels[i]),
             levels[i]-inter_time,
             levels[i])
            for i in xrange(len(polygons))
            ]  # label, lower bound, upper bound
        colors = get_isochrones_colors(len(levels))
        ranges = []
        for ix, cat in enumerate(cats):
            symbol = QgsFillSymbolV2()
            symbol.setColor(QtGui.QColor(colors[ix]))
            rng = QgsRendererRangeV2(cat[1], cat[2], symbol, cat[0])
            ranges.append(rng)

        expression = 'max'
        renderer = QgsGraduatedSymbolRendererV2(expression, ranges)

        isochrone_layer.setRendererV2(renderer)
        isochrone_layer.setLayerTransparency(25)
        self.iface.messageBar().clearWidgets()
        QgsMapLayerRegistry.instance().addMapLayer(isochrone_layer)
        self.iface.setActiveLayer(isochrone_layer)

    @lru_cache(maxsize=20)
    def prep_accessibility_old_osrm(self, point, url, inter_time, max_time):
        """Make the regular grid of points, snap them and compute tables"""
        try:
            conn = HTTPConnection(self.host)
        except Exception as err:
            self.display_error(err, 1)
            return -1

        bounds = get_search_frame(point, max_time)
        coords_grid = make_regular_points(bounds, self.max_points)
        self.progress.setValue(0.1)
        coords = list(set(
            [tuple(h_locate(pt, conn, self.http_headers)
                   ['mapped_coordinate'][::-1]) for pt in coords_grid]))
        origin_pt = h_locate(
            point, conn, self.http_headers)['mapped_coordinate'][::-1]

        self.progress.setValue(0.2)

        try:
            times = np.ndarray([])
            for nbi, chunk in enumerate(chunk_it(coords, 99)):
                matrix = h_light_table(
                    list(chunk) + [origin_pt], conn, self.http_headers)
                times = np.append(times, (matrix[-1])[:len(chunk)])
                self.progress.setValue((nbi + 1) / 2.0)
        except Exception as err:
            self.display_error(err, 1)
            conn.close()
            return

        conn.close()
        times = (times[1:] / 600.0).round(2)
        nb_inter = int(round(max_time / inter_time)) + 1
        levels = [nb for nb in xrange(0, int(
            round(np.nanmax(times)) + 1) + inter_time, inter_time)][:nb_inter]
        del matrix
        collec_poly = interpolate_from_times(times, coords, levels)
        self.progress.setValue(5.5)
        _ = levels.pop(0)
        polygons = qgsgeom_from_mpl_collec(collec_poly.collections)
        return polygons, levels

    @lru_cache(maxsize=20)
    def prep_accessibility_new_osrm(self, points, url, inter_time, max_time):
        """
        Make the regular grid of points and compute a table between them and
        and the source point, using the new OSRM table function for
        rectangular matrix
        + experimental support for polycentric accessibility isochrones
        (or multiple isochrones from multiple origine in one time...)
        """
        try:
            conn = HTTPConnection(self.host)
        except Exception as err:
            self.display_error(err, 1)
            return -1

        polygons = []
        points = [points] if isinstance(points[0], float) else points
        if len(points) > 1:
            self.max_points = 6500
        prog_val = 1
        for nb, point in enumerate(points):
            bounds = get_search_frame(point, max_time)
            coords_grid = make_regular_points(bounds, self.max_points)
            prog_val += 0.1 * (nb/len(points))
            self.progress.setValue(prog_val)

            matrix, src_coords, snapped_dest_coords = rectangular_light_table(
                point, coords_grid, conn, self.http_headers)
#            snapped_dest_coords.extend(tmp)
#            times = np.append(times, (matrix[0] / 600.0).round(2)[:])
            times = (matrix[0] / 600.0).round(2)
            prog_val += 4 * (nb/len(points))
            self.progress.setValue(prog_val)
            nb_inter = int(round(max_time / inter_time)) + 1
            levels = [nb for nb in xrange(0, int(
                round(np.nanmax(times)) + 1) + inter_time, inter_time)][:nb_inter]
            del matrix
            collec_poly = interpolate_from_times(
                times, [(i[1], i[0]) for i in snapped_dest_coords], levels)
            prog_val += 7 * (nb/len(points))
            self.progress.setValue(7)
            _ = levels.pop(0)
            polygons.append(qgsgeom_from_mpl_collec(collec_poly.collections))

        conn.close()

        if len(points) > 1:
            tmp = len(polygons[0])
            assert all([len(x) == tmp for x in polygons])
            polygons = np.array(polygons).transpose().tolist()
            print(polygons)
            merged_poly = [QgsGeometry.unaryUnion(polys) for polys in polygons]
            return merged_poly, levels
        else:
            return polygons[0], levels


class OSRM_batch_route_Dialog(QtGui.QDialog, FORM_CLASS_b, TemplateOsrm):
    def __init__(self, iface, parent=None):
        """Constructor."""
        super(OSRM_batch_route_Dialog, self).__init__(parent)
        self.setupUi(self)
        self.iface = iface
        self.http_headers = HTTP_HEADERS
        self.ComboBoxOrigin.setFilters(QgsMapLayerProxyModel.PointLayer)
        self.ComboBoxDestination.setFilters(QgsMapLayerProxyModel.PointLayer)
        self.ComboBoxCsv.setFilters(QgsMapLayerProxyModel.NoGeometry)
        self.pushButtonReverse.clicked.connect(self.reverse_OD_batch)
        self.pushButtonBrowse.clicked.connect(self.output_dialog_geo)
        self.pushButtonRun.clicked.connect(self.get_batch_route)
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

    def output_dialog_geo(self):
        self.lineEdit_output.clear()
        self.filename, self.encoding = save_dialog_geo()
        if self.filename is None:
            return
        self.lineEdit_output.setText(self.filename)

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
                self.display_error(err, 1)
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
                self.display_error("Too many errors occured when trying to "
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
