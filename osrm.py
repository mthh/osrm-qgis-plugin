# -*- coding: utf-8 -*-
"""
/***************************************************************************
 OSRM
                                 A QGIS plugin
 Display your routing results from OSRM
                              -------------------
        begin                : 2015-10-29
        git sha              : $Format:%H$
        copyright            : (C) 2015 by mthh
        email                :
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
from qgis.core import *
from qgis.utils import iface
from qgis.gui import QgsMapToolEmitPoint, QgsMapLayerProxyModel

from PyQt4.QtCore import (
    QTranslator, qVersion, QCoreApplication,
    QObject, SIGNAL, Qt, pyqtSlot
    )
from PyQt4.QtGui import (
    QAction, QIcon, QMessageBox,
    QColor, QProgressBar
    )
# Initialize Qt resources from file resources.py
import resources

# Import the code for the dialog
from osrm_dialog import (
    OSRMDialog, OSRM_table_Dialog, OSRM_access_Dialog, OSRM_batch_route_Dialog
    )

from .osrm_utils import *
from codecs import open as codecs_open
from sys import version_info
from httplib import HTTPConnection
import os.path
import json
import numpy as np
import csv


class OSRM(object):
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface
        self.canvas = iface.mapCanvas()
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'OSRM_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)

            if qVersion() > '4.3.3':
                QCoreApplication.installTranslator(self.translator)

        # Create the dialog (after translation) and keep reference
        self.dlg_route = OSRMDialog()
        self.dlg_table = OSRM_table_Dialog()
        self.dlg_access = OSRM_access_Dialog()
        self.dlg_batch_route = OSRM_batch_route_Dialog()
        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&Routing with OSRM')

        self.toolbar = self.iface.addToolBar(u'Routing with OSRM')
        self.toolbar.setObjectName(u'Routing with OSRM')
#        self.loadSettings()
        self.host = None
        self.http_header = {
            'connection': 'keep-alive',
            'User-Agent': ' '.join([
                'QGIS-desktop',
                QGis.QGIS_VERSION,
                '/',
                'Python-httplib',
                str(version_info[:3])[1:-1].replace(', ', '.')])
            }
    # noinspection PyMethodMayBeStatic

    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('Routing with OSRM', message)

    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.iface.addPluginToWebMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        self.add_action(
            ':/plugins/OSRM/img/icon.png',
            text=self.tr(u'Find a route with OSRM'),
            callback=self.run_route,
            parent=self.iface.mainWindow())

        self.add_action(
            ':/plugins/OSRM/img/icon_table.png',
            text=self.tr(u'Get a time matrix with OSRM'),
            callback=self.run_table,
            parent=self.iface.mainWindow())

        self.add_action(
            ':/plugins/OSRM/img/icon_access.png',
            text=self.tr(u'Make accessibility isochrones with OSRM'),
            callback=self.run_accessibility,
            parent=self.iface.mainWindow(),
            )

        self.add_action(
            None,
            text=self.tr(u'Export many routes from OSRM'),
            callback=self.run_batch_route,
            parent=self.iface.mainWindow(),
            add_to_toolbar=False,
            )  # ':/plugins/OSRM/img/icon_batchroute.png'

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginWebMenu(
                self.tr(u'&Routing with OSRM'),
                action)
            self.iface.removeToolBarIcon(action)
        # remove the toolbar
        del self.toolbar

    def store_origin(self, point):
        if '4326' not in self.canvas.mapSettings().destinationCrs().authid():
            crsSrc = self.canvas.mapSettings().destinationCrs()
            xform = QgsCoordinateTransform(
                crsSrc, QgsCoordinateReferenceSystem(4326))
            point = xform.transform(point)
        self.origin = point
        self.canvas.unsetMapTool(self.originEmit)
        self.dlg.lineEdit_xyO.setText(str(point))

    def store_destination(self, point):
        if '4326' not in self.canvas.mapSettings().destinationCrs().authid():
            crsSrc = self.canvas.mapSettings().destinationCrs()
            xform = QgsCoordinateTransform(
                crsSrc, QgsCoordinateReferenceSystem(4326))
            point = xform.transform(point)
        self.destination = point
        self.canvas.unsetMapTool(self.destinationEmit)
        self.dlg.lineEdit_xyD.setText(str(point))

    def get_origin(self):
        self.canvas.setMapTool(self.originEmit)

    def get_destination(self):
        self.canvas.setMapTool(self.destinationEmit)

    def reverse_OD(self):
        if len(self.dlg.lineEdit_xyO.text()) > 0 \
                and len(self.dlg.lineEdit_xyD.text()) > 0:
            tmp = self.dlg.lineEdit_xyO.text()
            tmp1 = self.dlg.lineEdit_xyD.text()
            self.dlg.lineEdit_xyD.setText(str(tmp))
            self.dlg.lineEdit_xyO.setText(str(tmp1))

    def clear_all_single(self):
        self.dlg_route.lineEdit_xyO.setText('')
        self.dlg_route.lineEdit_xyD.setText('')
        for layer in QgsMapLayerRegistry.instance().mapLayers():
            if 'route_osrm' in layer \
                    or 'instruction_osrm' in layer \
                    or 'markers_osrm' in layer:
                QgsMapLayerRegistry.instance().removeMapLayer(layer)
        self.nb_route = 0

    def clear_all_routes(self):
        for layer in QgsMapLayerRegistry.instance().mapLayers():
            if 'routes_osrm' in layer:
                QgsMapLayerRegistry.instance().removeMapLayer(layer)
        self.nb_done = 0

    def clear_all_isochrone(self):
        self.dlg.lineEdit_xyO.setText('')
        self.nb_isocr = 0
        for layer in QgsMapLayerRegistry.instance().mapLayers():
            if 'isochrone_osrm' in layer:
                QgsMapLayerRegistry.instance().removeMapLayer(layer)

    @pyqtSlot()
    def print_about(self):
        mbox = QMessageBox(self.iface.mainWindow())
        mbox.setIcon(QMessageBox.Information)
        mbox.setWindowTitle('About')
        mbox.setTextFormat(Qt.RichText)
        mbox.setText(
            "<p><b>(Unofficial) OSRM plugin for qgis</b><br><br>"
            "Author: mthh, 2015<br>Licence : GNU GPL v2<br><br><br>Underlying "
            "routing engine is <a href='http://project-osrm.org'>OSRM</a>"
            "(Open Source Routing Engine) :<br>- Based on OpenStreetMap "
            "dataset<br>- Easy to start a local instance<br>"
            "- Pretty fast engine (based on contraction hierarchies and mainly"
            " writen in C++)<br>- Mainly authored by D. Luxen and C. "
            "Vetter<br>(<a href='http://project-osrm.org'>http://project-osrm"
            ".org</a> or <a href='https://github.com/Project-OSRM/osrm"
            "-backend#references-in-publications'>on GitHub</a>)<br></p>")
        mbox.open()

    @lru_cache(maxsize=50)
    def query_url(self, url, host):
        self.conn.request('GET', url, headers=self.http_header)
        parsed = json.loads(self.conn.getresponse().read().decode('utf-8'))
        return parsed

    @pyqtSlot()
    def get_route(self):
        self._check_host()
        origin = self.dlg_route.lineEdit_xyO.text()
        destination = self.dlg_route.lineEdit_xyD.text()
        if len(origin) < 4 or len(destination) < 4:
            self.iface.messageBar().pushMessage("Error",
                                                "No coordinates selected!",
                                                duration=10)
            return
        try:
            xo, yo = eval(origin)
            xd, yd = eval(destination)
        except:
            self.iface.messageBar().pushMessage("Error", "Invalid coordinates",
                                                duration=10)
        url = ''.join(["/viaroute?loc={},{}&loc={},{}".format(yo, xo, yd, xd),
                       "&instructions={}&alt={}".format(
            str(self.dlg_route.checkBox_instruction.isChecked()).lower(),
            str(self.dlg_route.checkBox_alternative.isChecked()).lower())])

        try:
            self.conn = HTTPConnection(self.host)
            self.parsed = self.query_url(url, self.host)
            self.conn.close()
        except Exception as err:
            self._display_error(err, 1)
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
        self.prepare_route_symbol()
        osrm_route_layer.setRendererV2(QgsSingleSymbolRendererV2(self.my_symb))
        QgsMapLayerRegistry.instance().addMapLayer(osrm_route_layer)
        provider = osrm_route_layer.dataProvider()
        fet = QgsFeature()
        fet.setGeometry(line_geom)
        fet.setAttributes([0, self.parsed['route_summary']['total_time'],
                           self.parsed['route_summary']['total_distance']])
        provider.addFeatures([fet])

        self.make_OD_markers(xo, yo, xd, yd)
        osrm_route_layer.updateExtents()
        self.iface.setActiveLayer(osrm_route_layer)
        self.iface.zoomToActiveLayer()

        if self.dlg_route.checkBox_instruction.isChecked():
            pr_instruct, instruct_layer = self.prep_instruction()
            QgsMapLayerRegistry.instance().addMapLayer(instruct_layer)
            self.iface.setActiveLayer(instruct_layer)

        if self.dlg.checkBox_alternative.isChecked() \
                and 'alternative_geometries' in self.parsed:
            self.nb_alternative = len(self.parsed['alternative_geometries'])
            self.get_alternatives(provider)
            if self.dlg_route.checkBox_instruction.isChecked():
                for i in range(self.nb_alternative):
                    pr_instruct, instruct_layer = \
                       self.prep_instruction(i + 1, pr_instruct, instruct_layer)
        return

    def run_route(self):
        """Run the window to compute a single viaroute"""
        self.dlg = self.dlg_route
        self.origin = None
        self.destination = None
        self.nb_route = 0
        self.originEmit = QgsMapToolEmitPoint(self.canvas)
        self.destinationEmit = QgsMapToolEmitPoint(self.canvas)
        QObject.connect(
            self.originEmit,
            SIGNAL("canvasClicked(const QgsPoint&, Qt::MouseButton)"),
            self.store_origin)
        QObject.connect(
            self.destinationEmit,
            SIGNAL("canvasClicked(const QgsPoint&, Qt::MouseButton)"),
            self.store_destination)
        self.dlg.pushButtonOrigin.clicked.connect(self.get_origin)
        self.dlg.pushButtonDest.clicked.connect(self.get_destination)
        self.dlg.pushButtonReverse.clicked.connect(self.reverse_OD)
        self.dlg.pushButtonTryIt.clicked.connect(self.get_route)
        self.dlg.pushButtonClear.clicked.connect(self.clear_all_single)
        self.dlg.pushButton_about.clicked.connect(self.print_about)
        self.dlg.show()

    def prepare_route_symbol(self):
        colors = ['#1f78b4', '#ffff01', '#ff7f00',
                  '#fb9a99', '#b2df8a', '#e31a1c']
        p = self.nb_route % len(colors)
        self.my_symb = QgsSymbolV2.defaultSymbol(1)
        self.my_symb.setColor(QColor(colors[p]))
        self.my_symb.setWidth(1.2)

    def make_OD_markers(self, xo, yo, xd, yd):
        OD_layer = QgsVectorLayer(
            "Point?crs=epsg:4326&field=id_route:integer&field=role:string(80)",
            "markers_osrm{}".format(self.nb_route), "memory")
        pr_pt = OD_layer.dataProvider()
        fet = QgsFeature()
        fet.setGeometry(QgsGeometry.fromPoint(QgsPoint(float(xo), float(yo))))
        fet.setAttributes([self.nb_route, 'Origin'])
        pr_pt.addFeatures([fet])
        fet = QgsFeature()
        fet.setGeometry(QgsGeometry.fromPoint(QgsPoint(float(xd), float(yd))))
        fet.setAttributes([self.nb_route, 'Destination'])
        pr_pt.addFeatures([fet])
        s1 = QgsMarkerSymbolV2.createSimple({'size': '4', 'color': '#50b56d'})
        s2 = QgsMarkerSymbolV2.createSimple({'size': '4', 'color': '#d31115'})
        cats = [QgsRendererCategoryV2("Origin", s1, "Origin"),
                QgsRendererCategoryV2("Destination", s2, "Destination")]
        renderer = QgsCategorizedSymbolRendererV2("", cats)
        renderer.setClassAttribute("role")
        OD_layer.setRendererV2(renderer)
        QgsMapLayerRegistry.instance().addMapLayer(OD_layer)
        self.iface.setActiveLayer(OD_layer)

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
            liste_coords = \
                decode_geom_to_pts(self.parsed['alternative_geometries'][alt - 1])
            pts_instruct = \
                pts_ref(self.parsed['alternative_instructions'][alt - 1])
            instruct = \
                self.parsed['alternative_instructions'][alt - 1]

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

    def run_batch_route(self):
        """Run the window to compute many viaroute"""
        self.nb_done = 0
        self.dlg = self.dlg_batch_route

        self.dlg.ComboBoxOrigin.setFilters(
            QgsMapLayerProxyModel.PointLayer)
        self.dlg.ComboBoxDestination.setFilters(
            QgsMapLayerProxyModel.PointLayer)
        self.dlg.ComboBoxCsv.setFilters(
            QgsMapLayerProxyModel.NoGeometry)
        self.dlg.ComboBoxCsv.layerChanged.connect(
            self._set_layer_field_combo)

        self.dlg.check_two_layers.stateChanged.connect(
            lambda st: self.dlg.check_csv.setCheckState(0) if (
                st == 2 and self.dlg.check_csv.isChecked()) else None)
        self.dlg.check_csv.stateChanged.connect(
            lambda st: self.dlg.check_two_layers.setCheckState(0) if (
                st == 2 and self.dlg.check_two_layers.isChecked()) else None)

        self.dlg.pushButton_about.clicked.connect(self.print_about)
        self.dlg.pushButtonBrowse.clicked.connect(self.output_dialog_geo)
        self.dlg.pushButtonReverse.clicked.connect(self.reverse_OD_batch)
        self.dlg.pushButtonRun.clicked.connect(self.get_batch_route)
        self.dlg.show()

    def _prepare_queries(self):
        """Get the coordinates for each viaroute to query"""
        if self.dlg.check_two_layers.isChecked():
            origin_layer = self.dlg.ComboBoxOrigin.currentLayer()
            destination_layer = self.dlg.ComboBoxDestination.currentLayer()
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
                QMessageBox.information(
                    self.iface.mainWindow(), 'Info',
                    "Too many route to calculate, try with less than 100000")
                return -1

            return [(origin[1][1], origin[1][0], dest[1][1], dest[1][0])
                    for origin in origin_ids_coords
                    for dest in destination_ids_coords]

        elif self.dlg.check_csv.isChecked():
            layer = self.dlg.ComboBoxCsv.currentLayer()
            xo_col = self.dlg.FieldOriginX.currentField()
            yo_col = self.dlg.FieldOriginY.currentField()
            xd_col = self.dlg.FieldDestinationX.currentField()
            yd_col = self.dlg.FieldDestinationY.currentField()
            return [(str(ft.attribute(yo_col)), str(ft.attribute(xo_col)),
                     str(ft.attribute(yd_col)), str(ft.attribute(xd_col)))
                    for ft in layer.getFeatures()]
        else:
            QMessageBox.information(
                self.iface.mainWindow(), 'Error',
                "Choose a method between points layers / csv file")
            return -1

    @pyqtSlot()
    def get_batch_route(self):
        """Query the API and make a line for each route"""
        self.filename = self.dlg.lineEdit_output.text()
        if not self.dlg.check_add_layer.isChecked() \
                and '.shp' not in self.filename:
            QMessageBox.information(
                self.iface.mainWindow(), 'Error',
                "Output have to be saved and/or added to the canvas")
            return -1
        self._check_host()
        self.nb_route, errors, consec_errors = 0, 0, 0
        queries = self._prepare_queries()
        try:
            nb_queries = len(queries)
        except TypeError:
            return -1
        if nb_queries < 1:
            QMessageBox.information(
                self.iface.mainWindow(), 'Info',
                "Something wrong append - No locations to request"
                .format(self.filename))
            return -1
        elif nb_queries > 500 and 'project-osrm' in self.host:
            QMessageBox.information(
                self.iface.mainWindow(), 'Error',
                "Please, don't make heavy requests on the public API")
            return -1
        self._make_prog_bar()
        self.progress.setValue(0.1)
        self.conn = HTTPConnection(self.host)
        features = []
        for yo, xo, yd, xd in queries:
            try:
                url = (
                    "/viaroute?loc={},{}&loc={},{}"
                    "&instructions=false&alt=false").format(yo, xo, yd, xd)
                self.parsed = self.query_url(url, self.host)
            except Exception as err:
                self._display_error(err, 1)
                errors += 1
                consec_errors += 1
                continue
#            else:
            try:
                line_geom = decode_geom(self.parsed['route_geometry'])
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
                self.parsed['route_summary']['total_time'],
                self.parsed['route_summary']['total_distance']
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
            self.progress.setValue((
                (self.nb_route + errors) * 10 / nb_queries) - 1)
        self.conn.close()
        self.nb_done += 1

        if len(features) < 1:
            QMessageBox.information(
                self.iface.mainWindow(), 'Info',
                "Something wrong append - No feature fetched"
                .format(self.filename))
            return -1
        else:
            self.return_batch_route(features)
            return

    def return_batch_route(self, features):
        """Save and/or display the routes retrieved"""
        osrm_batch_route_layer = QgsVectorLayer(
            "Linestring?crs=epsg:4326&field=id:integer"
            "&field=total_time:integer(20)&field=distance:integer(20)",
            "routes_osrm{}".format(self.nb_done), "memory")
        provider = osrm_batch_route_layer.dataProvider()
        provider.addFeatures(features)
        QgsMapLayerRegistry.instance().addMapLayer(osrm_batch_route_layer)
        self.progress.setValue(9.5)
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
                QMessageBox.information(
                    self.iface.mainWindow(), 'Info',
                    "Result saved in {}".format(self.filename))
        if self.dlg.check_add_layer.isChecked():
            self.iface.setActiveLayer(osrm_batch_route_layer)
        else:
            QgsMapLayerRegistry.instance().removeMapLayer(
                osrm_batch_route_layer.id())
        self.iface.messageBar().clearWidgets()

    def run_table(self):
        """Run the window for the table function"""
        self.dlg = self.dlg_table
        self.dlg.pushButton_fetch.setDisabled(True)
        self.dlg.comboBox_layer.setFilters(QgsMapLayerProxyModel.PointLayer)
        self.dlg.pushButton_about.clicked.connect(self.print_about)
        self.dlg.pushButton_browse.clicked.connect(self.output_dialog)
        self.dlg.pushButton_fetch.clicked.connect(self.get_table)
        self.dlg.show()
        self.dlg_table.comboBox_layer.layerChanged.connect(
            lambda x: self.dlg_table.comboBox_idfield.setLayer(x)
            )
        self.dlg_table.lineEdit_output.textChanged.connect(
            lambda x: self.dlg.pushButton_fetch.setEnabled(True)
            if '.csv' in x else self.dlg.pushButton_fetch.setDisabled(True)
            )

    @pyqtSlot()
    def get_table(self):
        self._check_host()
        self.filename = self.dlg.lineEdit_output.text()
        s_layer = self.dlg.comboBox_layer.currentLayer()

        if '4326' not in s_layer.crs().authid():
            xform = QgsCoordinateTransform(
                s_layer.crs(), QgsCoordinateReferenceSystem(4326))
            coords = [xform.transform(ft.geometry().asPoint())
                      for ft in s_layer.getFeatures()]
        else:
            coords = [ft.geometry().asPoint() for ft in s_layer.getFeatures()]

        field = self.dlg.comboBox_idfield.currentField()
#        print(self.encoding)
        if field != '':
#            for ft in s_layer.getFeatures():
#                print(ft.attribute(field))
            ids = [ft.attribute(field) for ft in s_layer.getFeatures()]
        else:
            ids = [ft.id() for ft in s_layer.getFeatures()]

        try:
            conn = HTTPConnection(self.host)
            table = h_light_table(coords, conn, headers=self.http_header)
            conn.close()
        except ValueError as err:
            self._display_error(err, 1)
            return
        except Exception as er:
            self._display_error(er, 1)

        if len(table) < len(coords):
            self.iface.messageBar().pushMessage(
                'The array returned by OSRM is smaller to the size of the '
                'array requested\nOSRM parameter --max-table-size should '
                'be increased', duration=20)
        if self.dlg.checkBox_minutes.isChecked():
            table = np.array(table, dtype='float64')
            table = (table / 600.0).round(1)

        try:
            out_file = codecs_open(self.filename, 'w', encoding=self.encoding)
            writer = csv.writer(out_file, lineterminator='\n')
            if self.dlg.checkBox_flatten.isChecked():
                table = table.ravel()
                idsx = [(i, j)
                        for i in ids for j in ids]
                writer.writerow([u'Origin',
                                 u'Destination',
                                 u'Time'])
                writer.writerows([
                    [idsx[i][0], idsx[i][1], table[i]] for i in xrange(len(idsx))
                    ])
            else:
                writer.writerow([u''] + ids)
                writer.writerows(
                    [[ids[_id]] + line for _id, line in enumerate(table
                                                                  .tolist())])
            out_file.close()
            QMessageBox.information(
                self.iface.mainWindow(), 'Done',
                "OSRM table saved in {}".format(self.filename))
        except Exception as err:
            QMessageBox.information(
                self.iface.mainWindow(), 'Error',
                "Something went wrong...")
            QgsMessageLog.logMessage(
                'OSRM-plugin error report :\n {}'.format(err),
                level=QgsMessageLog.WARNING)

    def run_accessibility(self):
        """Run the window for making accessibility isochrones"""
        self.dlg = self.dlg_access
        self.originEmit = QgsMapToolEmitPoint(self.canvas)
        self.nb_isocr = 0
        QObject.connect(
            self.originEmit,
            SIGNAL("canvasClicked(const QgsPoint&, Qt::MouseButton)"),
            self.store_origin
            )
        self.dlg.pushButtonOrigin.clicked.connect(self.get_origin)
        self.dlg.pushButton_about.clicked.connect(self.print_about)
        self.dlg.pushButtonClear.clicked.connect(self.clear_all_isochrone)
        self.dlg.pushButton_fetch.clicked.connect(self.get_access_isochrones)
        self.dlg.show()

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
        self._check_host()
        self.max_points = 480
        origin = self.dlg.lineEdit_xyO.text()
        if len(origin) < 4:
            self.iface.messageBar().pushMessage(
                "Error", "No coordinates selected!", duration=10)
            return
        try:
            origin = eval(origin)
        except:
            self.iface.messageBar().pushMessage("Error", "Invalid coordinates",
                                                duration=10)
            return -1

        max_time = self.dlg.spinBox_max.value()
        inter_time = self.dlg.spinBox_intervall.value()
        self._make_prog_bar()
        polygons, levels = self.prep_accessibility(
            origin, self.host, inter_time, max_time)

        isochrone_layer = QgsVectorLayer(
            "MultiPolygon?crs=epsg:4326&field=id:integer"
            "&field=min:integer(10)"
            "&field=max:integer(10)",
            "isochrone_osrm_{}".format(self.nb_isocr), "memory")
        data_provider = isochrone_layer.dataProvider()

        features = []
        self.progress.setValue(9.5)
        for i, poly in enumerate(polygons):
            ft = QgsFeature()
            ft.setGeometry(poly)
            ft.setAttributes([i, levels[i] - inter_time, levels[i]])
            features.append(ft)
        data_provider.addFeatures(features[::-1])
        self.nb_isocr += 1

        symbol =  QgsFillSymbolV2()
        colorRamp = QgsVectorGradientColorRampV2.create(
            {'color1' : '#006837',
             'color2' : '#bb2921',
             'stops' : '0.5;#fff6a0'})
        renderer = QgsGraduatedSymbolRendererV2.createRenderer(
            isochrone_layer, 'max', len(levels),
            QgsGraduatedSymbolRendererV2.EqualInterval,
            symbol, colorRamp)

        isochrone_layer.setRendererV2(renderer)
        isochrone_layer.setLayerTransparency(10)
        self.iface.messageBar().clearWidgets()
        QgsMapLayerRegistry.instance().addMapLayer(isochrone_layer)
        self.iface.setActiveLayer(isochrone_layer)

    @lru_cache(maxsize=25)
    def prep_accessibility(self, point, url, inter_time, max_time):
        """Make the regular grid of points, snap them and compute tables"""
        try:
            conn = HTTPConnection(self.host)
        except Exception as err:
            self._display_error(err, 1)
            return -1

        bounds = get_search_frame(point, max_time)
        coords_grid = make_regular_points(bounds, self.max_points)
        self.progress.setValue(0.1)
        coords = list(set(
            [tuple(h_locate(pt, conn, self.http_header)
                   ['mapped_coordinate'][::-1]) for pt in coords_grid]))
        origin_pt = h_locate(
            point, conn, self.http_header)['mapped_coordinate'][::-1]
#        chunked_liste = chunk_it(coords, 99)
        self.progress.setValue(0.2)
        try:
            times = np.ndarray([])
            for nbi, chunk in enumerate(chunk_it(coords, 99)):
                matrix = h_light_table(
                    list(chunk) + [origin_pt], conn, self.http_header)
                times = np.append(times, (matrix[-1])[:len(chunk)])
                self.progress.setValue((nbi + 1) / 2.0)
        except Exception as err:
            self._display_error(err, 1)
            conn.close()
            return

        conn.close()
        times = (times[1:] / 600.0).round(0)
        nb_inter = int(round(max_time / inter_time)) + 1
        levels = [nb for nb in xrange(0, int(
            round(np.nanmax(times)) + 1) + inter_time, inter_time)][:nb_inter]
        del matrix
        collec_poly = interpolate_from_times(times, coords, levels)
        self.progress.setValue(5.5)
        _ = levels.pop(0)
        polygons = qgsgeom_from_mpl_collec(collec_poly.collections)
        return polygons, levels

    def reverse_OD_batch(self):
        if self.dlg.check_csv.isChecked():
            self.switch_OD_fields()
        elif self.dlg.check_two_layers.isChecked():
            self.swtich_OD_box()
        else:
            self.switch_OD_fields()
            self.swtich_OD_box()

    def switch_OD_fields(self):
        try:
            oxf = self.dlg.FieldOriginX.currentField()
            self.dlg.FieldOriginX.setField(
                self.dlg.FieldDestinationX.currentField())
            oyf = self.dlg.FieldOriginY.currentField()
            self.dlg.FieldOriginY.setField(
                self.dlg.FieldDestinationY.currentField())
            self.dlg.FieldDestinationX.setField(oxf)
            self.dlg.FieldDestinationY.setField(oyf)
        except Exception as err:
            QgsMessageLog.logMessage(
                'OSRM-plugin error report :\n {}'.format(err),
                level=QgsMessageLog.WARNING)

    def swtich_OD_box(self):
        try:
            tmp_o = self.dlg.ComboBoxOrigin.currentLayer()
            tmp_d = self.dlg.ComboBoxDestination.currentLayer()
            self.dlg.ComboBoxOrigin.setLayer(tmp_d)
            self.dlg.ComboBoxDestination.setLayer(tmp_o)
        except Exception as err:
            QgsMessageLog.logMessage(
                'OSRM-plugin error report :\n {}'.format(err),
                level=QgsMessageLog.WARNING)

    def output_dialog(self):
        self.dlg.lineEdit_output.clear()
        self.filename, self.encoding = save_dialog()
        if self.filename is None:
            return
        self.dlg.lineEdit_output.setText(self.filename)

    def output_dialog_geo(self):
        self.dlg.lineEdit_output.clear()
        self.filename, self.encoding = save_dialog_geo()
        if self.filename is None:
            return
        self.dlg.lineEdit_output.setText(self.filename)

    def _set_layer_field_combo(self, layer):
        self.dlg.FieldOriginX.setLayer(layer)
        self.dlg.FieldOriginY.setLayer(layer)
        self.dlg.FieldDestinationX.setLayer(layer)
        self.dlg.FieldDestinationY.setLayer(layer)

    def _display_error(self, err, code):
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
            'OSRM-plugin error report :\n {}'.format(err),
            level=QgsMessageLog.WARNING)

    def _make_prog_bar(self):
        progMessageBar = self.iface.messageBar().createMessage(
            "Creation in progress...")
        self.progress = QProgressBar()
        self.progress.setMaximum(10)
        self.progress.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        progMessageBar.layout().addWidget(self.progress)
        self.iface.messageBar().pushWidget(
            progMessageBar, iface.messageBar().INFO)

    def _check_host(self):
        """ Helper function to get the hostname in desired format """
        tmp = self.dlg.lineEdit_host.text()
        if len(tmp) < 5:
            self.iface.messageBar().pushMessage(
                "Error", "Please provide a valid non-empty URL", duration=10)
            return
        if not ('http' in tmp and '//' in tmp) and tmp[-1] == '/':
            self.host = tmp[:-1]
        elif not ('http:' in tmp and '//' in tmp):
            self.host = tmp
        elif 'http://' in tmp[:7] and tmp[-1] == '/':
            self.host = tmp[7:-1]
        elif 'http://' in tmp[:7]:
            self.host = tmp[7:]
        else:
            self.host = tmp

# TODO :
# - ensure that the MapToolEmitPoint is unset when the plugin window is closed
# - use a graduated layer for displaying the isochrones
