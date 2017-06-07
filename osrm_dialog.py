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
        email                : matthieu.viry@cnrs.fr
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
import sys
import numpy as np

from PyQt4 import QtGui, uic
#from PyQt4.QtCore import Qt, QPointF, QThreadPool, QEventLoop
from re import match
from codecs import open as codecs_open
from multiprocessing.pool import ThreadPool
from qgis.gui import QgsMapLayerProxyModel, QgsMapToolEmitPoint
from qgis.core import (
    QgsMessageLog, QgsCoordinateTransform, QgsFeature,
    QgsCoordinateReferenceSystem, QgsMapLayerRegistry,
    QgsVectorLayer, QgsVectorFileWriter, QgsPoint,
    QgsGeometry, QgsRuleBasedRendererV2, QgsSymbolV2,
    QgsGraduatedSymbolRendererV2, QgsRendererRangeV2, QgsFillSymbolV2,
    QgsSingleSymbolRendererV2, QgsPalLayerSettings
    )
from osrm_utils import *
#from osrm_utils_extern import lru_cache
#from time import time as t_time

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'ui/osrm_dialog_base.ui'))

FORM_CLASS_t, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'ui/osrm_table_dialog_base.ui'))

FORM_CLASS_a, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'ui/osrm_access_dialog_base.ui'))

FORM_CLASS_b, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'ui/osrm_batch_route.ui'))

FORM_CLASS_tsp, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'ui/osrm_dialog_tsp.ui'))


class OSRM_DialogTSP(QtGui.QDialog, FORM_CLASS_tsp, TemplateOsrm):
    def __init__(self, iface, parent=None):
        """ Constructor"""
        super(OSRM_DialogTSP, self).__init__(parent)
        self.setupUi(self)
        self.iface = iface
        self.pushButton_display.clicked.connect(self.run_tsp)
        self.pushButton_clear.clicked.connect(self.clear_results)
        self.comboBox_layer.setFilters(QgsMapLayerProxyModel.PointLayer)
        self.nb_route = 0

    def clear_results(self):
        """
        Clear previous result and set back counter to 0.
        """
        for layer in QgsMapLayerRegistry.instance().mapLayers():
            if 'tsp_solution_osrm' in layer:
                QgsMapLayerRegistry.instance().removeMapLayer(layer)
        self.nb_route = 0

    def run_tsp(self):
        """
        Main method, preparing the query and displaying the result on
        the canvas.
        """
        layer = self.comboBox_layer.currentLayer()
        coords, _ = get_coords_ids(
            layer, '', on_selected=self.checkBox_selec_features.isChecked())

        if len(coords) < 2:
            return -1

        try:
            self.host = check_host(self.lineEdit_host.text())
            profile = check_profile_name(self.lineEdit_profileName.text())
        except (ValueError, AssertionError) as err:
            print(err)
            self.iface.messageBar().pushMessage(
                "Error",
                "Please provide a valid non-empty URL and profile name",
                duration=10)
            return

        query = ''.join(
            ["http://", self.host,
            "/trip/", profile, "/",
            ";".join(["{},{}".format(c[0], c[1]) for c in coords])])

        try:
            self.parsed = self.query_url(query)
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
                [decode_geom(self.parsed['trips'][i]['geometry'])
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
                              feature['distance'],
                              feature['duration']])
            features.append(ft)
            self.prepare_ordered_marker(coords, idx)
        tsp_route_layer.dataProvider().addFeatures(features)
        tsp_route_layer.updateExtents()
        QgsMapLayerRegistry.instance().addMapLayer(tsp_route_layer)
        self.iface.setActiveLayer(tsp_route_layer)
        self.iface.zoomToActiveLayer()
        put_on_top(self.tsp_marker_lr.id(), tsp_route_layer.id())
        self.nb_route += 1
#        if self.checkBox_instructions.isChecked():
#            pr_instruct, instruct_layer = self.prep_instruction()
#            QgsMapLayerRegistry.instance().addMapLayer(instruct_layer)
#            self.iface.setActiveLayer(instruct_layer)

    def prepare_ordered_marker(self, coords, idx):
        """
        Try to display nice marker on a point layer, showing the order of
        the path computed by OSRM.
        """
        self.tsp_marker_lr = QgsVectorLayer(
            "Point?crs=epsg:4326&field=id:integer"
            "&field=TSP_nb:integer(20)&field=Origin_nb:integer(20)",
            "tsp_markers_osrm{}".format(self.nb_route), "memory")
        symbol = QgsSymbolV2.defaultSymbol(self.tsp_marker_lr.geometryType())
        symbol.setSize(4.5)
        symbol.setColor(QtGui.QColor("yellow"))

        ordered_pts = \
            [coords[i["waypoint_index"]] for i in self.parsed['waypoints']]
        print("ordered_pts : ", ordered_pts)

        features = []
        for nb, pt in enumerate(ordered_pts):
            ft = QgsFeature()
            ft.setGeometry(QgsGeometry.fromPoint(QgsPoint(pt)))
            ft.setAttributes([nb, nb + 1, coords.index(pt)])
            features.append(ft)
        self.tsp_marker_lr.dataProvider().addFeatures(features)

        pal_lyr = QgsPalLayerSettings()
        pal_lyr.readFromLayer(self.tsp_marker_lr)
        pal_lyr.enabled = True
        pal_lyr.fieldName = 'TSP_nb'
        pal_lyr.placement = QgsPalLayerSettings.OverPoint
        pal_lyr.setDataDefinedProperty(
            QgsPalLayerSettings.Size, True, True, '12', '')
        pal_lyr.writeToLayer(self.tsp_marker_lr)

        self.tsp_marker_lr.setRendererV2(QgsSingleSymbolRendererV2(symbol))
        QgsMapLayerRegistry.instance().addMapLayer(self.tsp_marker_lr)


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
        """
        Fetch the geometry of alternatives roads if requested
        """
        for i, alt_geom in enumerate(self.parsed['routes'][1:]):
            decoded_alt_line = decode_geom(alt_geom["geometry"])
            fet = QgsFeature()
            fet.setGeometry(decoded_alt_line)
            fet.setAttributes([
                i + 1,
                alt_geom["duration"],
                alt_geom["distance"]
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
            if 'route_osrm' in layer or 'markers_osrm' in layer:
                    # or 'instruction_osrm' in layer \
                QgsMapLayerRegistry.instance().removeMapLayer(layer)
        self.nb_route = 0

    # def prep_instruction(self, alt=None, provider=None,
    #                      osrm_instruction_layer=None):
    #     """
    #     Prepare the instruction layer, each field corresponding to an OSRM
    #     viaroute response field.
    #     """
    #     if not alt:
    #         osrm_instruction_layer = QgsVectorLayer(
    #             "Point?crs=epsg:4326&field=id:integer&field=alt:integer"
    #             "&field=directions:integer(20)&field=street_name:string(254)"
    #             "&field=length:integer(20)&field=position:integer(20)"
    #             "&field=time:integer(20)&field=length:string(80)"
    #             "&field=direction:string(20)&field=azimuth:float(10,4)",
    #             "instruction_osrm{}".format(self.nb_route),
    #             "memory")
    #         liste_coords = decode_geom_to_pts(self.parsed['route_geometry'])
    #         pts_instruct = pts_ref(self.parsed['route_instructions'])
    #         instruct = self.parsed['route_instructions']
    #         provider = osrm_instruction_layer.dataProvider()
    #     else:
    #         liste_coords = decode_geom_to_pts(
    #             self.parsed['alternative_geometries'][alt - 1])
    #         pts_instruct = pts_ref(
    #             self.parsed['alternative_instructions'][alt - 1])
    #         instruct = self.parsed['alternative_instructions'][alt - 1]
    #
    #     for nbi, pt in enumerate(pts_instruct):
    #         fet = QgsFeature()
    #         fet.setGeometry(
    #             QgsGeometry.fromPoint(
    #                 QgsPoint(liste_coords[pt][0], liste_coords[pt][1])))
    #         fet.setAttributes([nbi, alt, instruct[nbi][0],
    #                            instruct[nbi][1], instruct[nbi][2],
    #                            instruct[nbi][3], instruct[nbi][4],
    #                            instruct[nbi][5], instruct[nbi][6],
    #                            instruct[nbi][7]])
    #         provider.addFeatures([fet])
    #     return provider, osrm_instruction_layer

    @staticmethod
    def make_OD_markers(nb, xo, yo, xd, yd, list_coords=None):
        """
        Prepare the Origin (green), Destination (red) and Intermediates (grey)
        markers.
        """
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
                    QgsGeometry.fromPoint(QgsPoint(float(pt[0]), float(pt[1])))
                    )
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

    def get_route(self):
        """
        Main method to prepare the request and display the result on the
        QGIS canvas.
        """
        try:
            self.host = check_host(self.lineEdit_host.text())
            profile = check_profile_name(self.lineEdit_profileName.text())
        except (ValueError, AssertionError) as err:
            print(err)
            self.iface.messageBar().pushMessage(
                "Error",
                "Please provide a valid non-empty URL and profile name",
                duration=10)
            return

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
                tmp = ';'.join(
                    ['{},{}'.format(xi, yi) for xi, yi in interm])
                url = ''.join([
                    "http://", self.host, "/route/", profile, "/",
                    "{},{};".format(xo, yo), tmp, ";{},{}".format(xd, yd),
                    "?overview=full&alternatives={}".format(
                        str(self.checkBox_alternative.isChecked()).lower())])
            except:
                self.iface.messageBar().pushMessage(
                    "Error", "Invalid intemediates coordinates", duration=10)
        else:
            url = ''.join([
                "http://", self.host, "/route/", profile, "/",
                "polyline(", encode_to_polyline([(yo, xo), (yd, xd)]), ")",
                "?overview=full&alternatives={}"
                .format(str(self.checkBox_alternative.isChecked()).lower())])

        try:
            self.parsed = self.query_url(url)
            assert "code" in self.parsed
        except Exception as err:
            self.display_error(err, 1)
            return

        if 'Ok' not in self.parsed['code']:
            self.display_error(self.parsed['code'], 1)
            return

        try:
            enc_line = self.parsed['routes'][0]["geometry"]
            line_geom = decode_geom(enc_line)
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
        provider = osrm_route_layer.dataProvider()
        fet = QgsFeature()
        fet.setGeometry(line_geom)
        fet.setAttributes([0, self.parsed['routes'][0]['duration'],
                           self.parsed['routes'][0]['distance']])
        provider.addFeatures([fet])
        OD_layer = self.make_OD_markers(self.nb_route, xo, yo, xd, yd, interm)
        QgsMapLayerRegistry.instance().addMapLayer(OD_layer)

        osrm_route_layer.updateExtents()
        QgsMapLayerRegistry.instance().addMapLayer(osrm_route_layer)
        self.iface.setActiveLayer(osrm_route_layer)
        self.iface.zoomToActiveLayer()
        put_on_top(OD_layer.id(), osrm_route_layer.id())
#        if self.checkBox_instruction.isChecked():
#            pr_instruct, instruct_layer = self.prep_instruction()
#            QgsMapLayerRegistry.instance().addMapLayer(instruct_layer)
#            self.iface.setActiveLayer(instruct_layer)

        if self.checkBox_alternative.isChecked() \
                and 'alternative_geometries' in self.parsed:
            self.nb_alternative = len(self.parsed['routes'] - 1)
            self.get_alternatives(provider)
#            if self.dlg.checkBox_instruction.isChecked():
#                for i in range(self.nb_alternative):
#                    pr_instruct, instruct_layer = \
#                       self.prep_instruction(
#                           i + 1, pr_instruct, instruct_layer)
        return


class OSRM_table_Dialog(QtGui.QDialog, FORM_CLASS_t, TemplateOsrm):
    def __init__(self, iface, parent=None):
        """Constructor."""
        super(OSRM_table_Dialog, self).__init__(parent)
        self.setupUi(self)
        self.iface = iface
        self.encoding = "System"
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

    def output_dialog(self):
        self.lineEdit_output.clear()
        self.filename, self.encoding = save_dialog()
        if self.filename is None:
            return
        self.lineEdit_output.setText(self.filename)

    def get_table(self):
        """
        Main method to prepare the query and fecth the table to a .csv file
        """
        try:
            self.host = check_host(self.lineEdit_host.text())
            profile = check_profile_name(self.lineEdit_profileName.text())
        except:
            self.iface.messageBar().pushMessage(
                "Error", "Please provide valid non-empty URL and profile name",
                duration=10)
            return

        self.filename = self.lineEdit_output.text()

        s_layer = self.comboBox_layer.currentLayer()
        d_layer = self.comboBox_layer_2.currentLayer() \
            if self.comboBox_layer_2.currentLayer() != s_layer else None

        coords_src, ids_src = \
            get_coords_ids(s_layer, self.comboBox_idfield.currentField())

        coords_dest, ids_dest = \
            get_coords_ids(d_layer, self.comboBox_idfield_2.currentField()) \
            if d_layer else (None, None)

        url = ''.join(["http://", self.host, '/table/', profile, '/'])

        try:
            table, new_src_coords, new_dest_coords = \
                    fetch_table(url, coords_src, coords_dest)
        except ValueError as err:
            print(err)
            self.display_error(err, 1)
            return
        except Exception as er:
            print(er)
            self.display_error(er, 1)
            return

        # Convert the matrix in minutes if needed :
        if self.checkBox_minutes.isChecked():
            table = (table / 60.0).round(2)

        # Replace the value corresponding to a not-found connection :
        if self.checkBox_empty_val.isChecked():
            if self.checkBox_minutes.isChecked():
                table[table == 3579139.4] = np.NaN
            else:
                table[table == 2147483647] = np.NaN

        # Fetch the default encoding if selected :
        if self.encoding == "System":
            self.encoding = sys.getdefaultencoding()

        # Write the result in csv :
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
            print(err)
            QtGui.QMessageBox.information(
                self.iface.mainWindow(), 'Error',
                "Something went wrong...(See Qgis log for traceback)")
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
        self.comboBox_pointlayer.setFilters(QgsMapLayerProxyModel.PointLayer)
        self.comboBox_method.activated[str].connect(self.enable_functionnality)
        self.pushButton_fetch.clicked.connect(self.get_access_isochrones)
        self.pushButtonClear.clicked.connect(self.clear_all_isochrone)
        self.lineEdit_xyO.textChanged.connect(self.change_nb_center)
        self.nb_isocr = 0
        self.host = None
        self.progress = None

    def change_nb_center(self):
        nb_center = self.lineEdit_xyO.text().count('(')
        self.textBrowser_nb_centers.setHtml(
            """<p style=" margin-top:0px; margin-bottom:0px;"""
            """margin-left:0px; margin-right:0px; -qt-block-indent:0; """
            """text-indent:0px;"><span style=" font-style:italic;">"""
            """{} center(s) selected</span></p>""".format(nb_center))

    def enable_functionnality(self, text):
        functions = (
            self.pushButtonOrigin.setEnabled,
            self.lineEdit_xyO.setEnabled,
            self.textBrowser_nb_centers.setEnabled,
            self.toolButton_poly.setEnabled,
            self.comboBox_pointlayer.setEnabled,
            self.label_3.setEnabled,
            self.checkBox_selectedFt.setEnabled,
            self.pushButton_fetch.setEnabled
        )
        if 'clicking' in text:
            values = (True, True, True, True, False, False, False, True)
        elif 'selecting' in text:
            values = (False, False, False, False, True, True, True, True)
        elif 'method' in text:
            values = (False, False, False, False, False, False, False, False)
        else:
            return
        for func, bool_value in zip(functions, values):
            func(bool_value)

    def clear_all_isochrone(self):
        """
        Clear previously done isochrone polygons and clear the coordinate field
        """
        self.lineEdit_xyO.setText('')
        self.nb_isocr = 0
        for layer in QgsMapLayerRegistry.instance().mapLayers():
            if 'isochrone_osrm' in layer or 'isochrone_center':
                QgsMapLayerRegistry.instance().removeMapLayer(layer)

    def store_intermediate_acces(self, point):
        if '4326' not in self.canvas.mapSettings().destinationCrs().authid():
            crsSrc = self.canvas.mapSettings().destinationCrs()
            xform = QgsCoordinateTransform(
                crsSrc, QgsCoordinateReferenceSystem(4326))
            point = xform.transform(point)
        tmp = self.lineEdit_xyO.text()
        self.change_nb_center()
        self.lineEdit_xyO.setText(', '.join([tmp, repr(point)]))

    def get_points_from_canvas(self):
        pts = self.lineEdit_xyO.text()
        try:
            assert match('^[^a-zA-Z]+$', pts) and len(pts) > 4
            pts = eval(pts)
            if len(pts) < 2:
                raise ValueError
            elif len(pts) == 2 and not isinstance(pts[0], tuple):
                assert isinstance(pts[0], (int, float))
                assert isinstance(pts[1], (int, float))
                pts = [pts]
            else:
                assert all([isinstance(pt, tuple) for pt in pts])
                assert all([isinstance(coord[0], (float, int)) &
                             isinstance(coord[1], (float, int))
                            for coord in pts])
            return pts
        except Exception as err:
            print(err)
            QtGui.QMessageBox.warning(
                self.iface.mainWindow(), 'Error',
                "Invalid coordinates selected!")
            return None

    def add_final_pts(self, pts):
        center_pt_layer = QgsVectorLayer(
            "Point?crs=epsg:4326&field=id_center:integer&field=role:string(80)",
            "isochrone_center_{}".format(self.nb_isocr), "memory")
        my_symb = QgsSymbolV2.defaultSymbol(0)
        my_symb.setColor(QtGui.QColor("#e31a1c"))
        my_symb.setSize(1.2)
        center_pt_layer.setRendererV2(QgsSingleSymbolRendererV2(my_symb))
        features = []
        for nb, pt in enumerate(pts):
            xo, yo = pt["point"]
            fet = QgsFeature()
            fet.setGeometry(QgsGeometry.fromPoint(
                QgsPoint(float(xo), float(yo))))
            fet.setAttributes([nb, 'Origin'])
            features.append(fet)
        center_pt_layer.dataProvider().addFeatures(features)
        QgsMapLayerRegistry.instance().addMapLayer(center_pt_layer)

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
            self.profile = check_profile_name(self.lineEdit_profileName.text())
        except (ValueError, AssertionError) as err:
            self.iface.messageBar().pushMessage(
                "Error", "Please provide a valid non-empty URL", duration=10)
            return

        if 'clicking' in self.comboBox_method.currentText():
            pts = self.get_points_from_canvas()
        elif 'selecting' in self.comboBox_method.currentText():
            layer = self.comboBox_pointlayer.currentLayer()
            pts, _ = get_coords_ids(
                layer, '', on_selected=self.checkBox_selectedFt.isChecked())
            pts = tuple(pts)

        if not pts:
            return

        max_time = self.spinBox_max.value()
        interval_time = self.spinBox_intervall.value()
        nb_inter = int(round(max_time / interval_time)) + 1
        levels = tuple([nb for nb in xrange(0, int(
            max_time + 1) + interval_time, interval_time)][:nb_inter])

        self.make_prog_bar()
        self.max_points = 750 if len(pts) == 1 else 250
        self.polygons = []

        pts = [{"point": pt, "max": max_time, "levels": levels,
                "host": self.host, "profile": self.profile,
                "max_points": self.max_points}
                for pt in pts]

        pool = ThreadPool(processes=4 if len(pts) >= 4 else len(pts))

        try:
            self.polygons = [i for i in pool.map(prep_access, pts)]
        except Exception as err:
            self.display_error(err, 1)
            return

        if len(self.polygons) == 1:
            self.polygons = self.polygons[0]
        else:
            self.polygons = np.array(self.polygons).transpose().tolist()
            self.polygons = \
                [QgsGeometry.unaryUnion(polys) for polys in self.polygons]

        isochrone_layer = QgsVectorLayer(
            "MultiPolygon?crs=epsg:4326&field=id:integer"
            "&field=min:integer(10)"
            "&field=max:integer(10)",
            "isochrone_osrm_{}".format(self.nb_isocr), "memory")
        data_provider = isochrone_layer.dataProvider()
        # Add the features to the layer to display :
        features = []
        levels = levels[1:]
        self.progress.setValue(8.5)
        for i, poly in enumerate(self.polygons):
            if not poly:
                continue
            ft = QgsFeature()
            ft.setGeometry(poly)
            ft.setAttributes(
                [i, levels[i] - interval_time, levels[i]])
            features.append(ft)
        data_provider.addFeatures(features[::-1])
        self.nb_isocr += 1
        self.progress.setValue(9.5)

        # Render the value :
        renderer = self.prepare_renderer(
            levels, interval_time, len(self.polygons))
        isochrone_layer.setRendererV2(renderer)
        isochrone_layer.setLayerTransparency(25)
        self.iface.messageBar().clearWidgets()
        QgsMapLayerRegistry.instance().addMapLayer(isochrone_layer)

        self.add_final_pts(pts)
        self.iface.setActiveLayer(isochrone_layer)

    @staticmethod
    def prepare_renderer(levels, inter_time, lenpoly):
        cats = [
            ('{} - {} min'.format(levels[i] - inter_time, levels[i]),
             levels[i] - inter_time,
             levels[i])
            for i in xrange(lenpoly)
            ]  # label, lower bound, upper bound
        colors = get_isochrones_colors(len(levels))
        ranges = []
        for ix, cat in enumerate(cats):
            symbol = QgsFillSymbolV2()
            symbol.setColor(QtGui.QColor(colors[ix]))
            rng = QgsRendererRangeV2(cat[1], cat[2], symbol, cat[0])
            ranges.append(rng)
        expression = 'max'
        return QgsGraduatedSymbolRendererV2(expression, ranges)


class OSRM_batch_route_Dialog(QtGui.QDialog, FORM_CLASS_b, TemplateOsrm):
    def __init__(self, iface, parent=None):
        """Constructor."""
        super(OSRM_batch_route_Dialog, self).__init__(parent)
        self.setupUi(self)
        self.iface = iface
        self.ComboBoxOrigin.setFilters(QgsMapLayerProxyModel.PointLayer)
        self.ComboBoxDestination.setFilters(QgsMapLayerProxyModel.PointLayer)
        self.ComboBoxCsv.setFilters(QgsMapLayerProxyModel.NoGeometry)
        self.pushButtonReverse.clicked.connect(self.reverse_OD_batch)
        self.pushButtonBrowse.clicked.connect(self.output_dialog_geo)
        self.pushButtonRun.clicked.connect(self.get_batch_route)
        self.comboBox_method.activated[str].connect(self.enable_functionnality)
        self.comboBox_host.activated[str].connect(self.add_host)
        self.ComboBoxCsv.layerChanged.connect(self._set_layer_field_combo)
        self.nb_done = 0

    def add_host(self, text):
        if "Add an url" in text:
            pass

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

    def enable_functionnality(self, text):
        functions = (
            self.ComboBoxOrigin.setEnabled, self.label_2.setEnabled,
            self.ComboBoxDestination.setEnabled, self.label.setEnabled,
            self.label_5.setEnabled, self.ComboBoxCsv.setEnabled,
            self.FieldOriginX.setEnabled, self.FieldOriginY.setEnabled,
            self.FieldDestinationX.setEnabled, self.label_6.setEnabled,
            self.FieldDestinationY.setEnabled, self.label_7.setEnabled,
            self.label_8.setEnabled, self.label_9.setEnabled
        )
        if 'layer' in text:
            values = (True, True, True, True,
                      False, False, False, False, False,
                      False, False, False, False, False)
        elif '.csv' in text:
            values = (False, False, False, False,
                      True, True, True, True, True,
                      True, True, True, True, True)
        elif 'method' in text:
            values = (False, False, False, False,
                      False, False, False, False, False,
                      False, False, False, False, False)
        else:
            return
        for func, bool_value in zip(functions, values):
            func(bool_value)

    def _prepare_queries(self):
        """Get the coordinates for each viaroute to query"""
        if self.ComboBoxOrigin.isEnabled():
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

        elif self.FieldOriginX.isEnabled():  # If the source file is a .csv :
            layer = self.ComboBoxCsv.currentLayer()
            xo_col = self.FieldOriginX.currentField()
            yo_col = self.FieldOriginY.currentField()
            xd_col = self.FieldDestinationX.currentField()
            yd_col = self.FieldDestinationY.currentField()
            return [(str(ft.attribute(yo_col)), str(ft.attribute(xo_col)),
                     str(ft.attribute(yd_col)), str(ft.attribute(xd_col)))
                    for ft in layer.getFeatures()]

            return -1

    def reverse_OD_batch(self):
        """Helper function to dispatch to the proper method"""
        if self.FieldOriginX.isEnabled():
            self.switch_OD_fields()
        elif self.ComboBoxOrigin.isEnabled():
            self.swtich_OD_box()
        else:
            self.switch_OD_fields()
            self.swtich_OD_box()

    def switch_OD_fields(self):
        """ Switch the selected fields from the csv file"""
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
        """ Switch the Origin and the Destination layer"""
        try:
            tmp_o = self.ComboBoxOrigin.currentLayer()
            tmp_d = self.ComboBoxDestination.currentLayer()
            self.ComboBoxOrigin.setLayer(tmp_d)
            self.ComboBoxDestination.setLayer(tmp_o)
        except Exception as err:
            QgsMessageLog.logMessage(
                'OSRM-plugin error report :\n {}'.format(err),
                level=QgsMessageLog.WARNING)

    def get_batch_route(self):
        #TODO: Deplacer le batch_route vers un Worker pour pas perdre le
        #  controle sur l'interface pendant le temps de calcul
        """Query the API and make a line for each route"""
        self.filename = self.lineEdit_output.text()
        if not self.check_add_layer.isChecked() \
                and '.shp' not in self.filename:
            QtGui.QMessageBox.information(
                self.iface.mainWindow(), 'Error',
                "Output have to be saved and/or added to the canvas")
            return -1
        try:
            self.host = check_host(self.comboBox_host.currentText())
            profile = check_profile_name(self.lineEdit_profileName.text())
        except (ValueError, AssertionError) as err:
            self.iface.messageBar().pushMessage(
                "Error", "Please provide a valid non-empty URL", duration=10)
            return

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
        elif nb_queries > 20 and 'project-osrm' in self.host:
            QtGui.QMessageBox.information(
                self.iface.mainWindow(), 'Error',
                "Please, don't make heavy requests on the public API")
            return -1

        self.make_prog_bar()
        features = []
        for yo, xo, yd, xd in queries:
            try:
                url = ''.join([
                    "http://", self.host, "/route/", profile, "/",
                    "{},{};{},{}".format(xo, yo, xd, yd),
                    "?overview=full&steps=false&alternatives=false"])
                parsed = self.query_url(url)
            except Exception as err:
                print(err)
                self.display_error(err, 1)
                errors += 1
                consec_errors += 1
                continue
            try:
                line_geom = decode_geom(parsed['routes'][0]["geometry"])
            except KeyError as err:
                print(err)
                self.iface.messageBar().pushMessage(
                    "Error",
                    "No route found between {} and {}"
                    .format((xo, yo), (xd, yd)),
                    duration=5)
                errors += 1
                consec_errors += 1
                continue
            fet = QgsFeature()
            fet.setGeometry(line_geom)
            fet.setAttributes([
                self.nb_route,
                parsed['routes'][0]['duration'],
                parsed['routes'][0]['distance']
                ])
            features.append(fet)
            consec_errors = 0
            self.nb_route += 1
            if consec_errors > 50:  # Avoid to continue to make wrong requests:
                self.conn.close()
                self.display_error("Too many errors occured when trying to "
                                   "contact the OSRM instance - Route calcula"
                                   "tion has been stopped ", 2)
                break
        self.nb_done += 1

        if len(features) < 1:
            QtGui.QMessageBox.information(
                self.iface.mainWindow(), 'Info',
                "Something wrong append - No feature fetched"
                .format(self.filename))
            return -1
        else:
            self.return_batch_route(features)

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
