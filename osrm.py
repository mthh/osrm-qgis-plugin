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
from PyQt4.QtCore import (
    QTranslator, qVersion, QCoreApplication,
    QObject, SIGNAL, Qt, pyqtSlot, QSettings
    )
from PyQt4.QtGui import (
    QAction, QIcon, QMessageBox,
    )
# Initialize Qt resources from file resources.py
import resources
import os.path
# Import the code for the dialog
from osrm_dialog import (
    OSRMDialog, OSRM_table_Dialog, OSRM_access_Dialog,
    OSRM_batch_route_Dialog, OSRM_DialogTSP
    )


class OSRM(object):
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        self.dlg = None
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

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&Routing with OSRM')

        self.toolbar = self.iface.addToolBar(u'Routing with OSRM')
        self.toolbar.setObjectName(u'Routing with OSRM')
#        self.loadSettings()
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
            text=self.tr(u'Solve the Traveling Salesman Problem with OSRM'),
            callback=self.run_tsp,
            parent=self.iface.mainWindow(),
            add_to_toolbar=False,
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

    @pyqtSlot()
    def run_route(self):
        """Run the window to compute a single viaroute"""
        self.dlg = OSRMDialog(iface)
        QObject.connect(
            self.dlg.originEmit,
            SIGNAL("canvasClicked(const QgsPoint&, Qt::MouseButton)"),
            self.dlg.store_origin)
        QObject.connect(
            self.dlg.intermediateEmit,
            SIGNAL("canvasClicked(const QgsPoint&, Qt::MouseButton)"),
            self.dlg.store_intermediate)
        QObject.connect(
            self.dlg.destinationEmit,
            SIGNAL("canvasClicked(const QgsPoint&, Qt::MouseButton)"),
            self.dlg.store_destination)
        self.dlg.pushButtonOrigin.clicked.connect(self.get_origin)
        self.dlg.pushButtonIntermediate.clicked.connect(self.get_intermediate)
        self.dlg.pushButtonDest.clicked.connect(self.get_destination)
        self.dlg.pushButton_about.clicked.connect(self.dlg.print_about)
        self.dlg.show()

    @pyqtSlot()
    def run_batch_route(self):
        """Run the window to compute many viaroute"""
        self.nb_done = 0
        self.dlg = OSRM_batch_route_Dialog(iface)
        self.dlg.pushButton_about.clicked.connect(self.dlg.print_about)
        self.dlg.show()

    @pyqtSlot()
    def run_table(self):
        """Run the window for the table function"""
        self.dlg = OSRM_table_Dialog(iface)
        self.dlg.pushButton_about.clicked.connect(self.dlg.print_about)
        self.dlg.show()

    @pyqtSlot()
    def run_tsp(self):
        """Run the window for making accessibility isochrones"""
        self.dlg = OSRM_DialogTSP(iface)
        self.dlg.pushButton_about.clicked.connect(self.dlg.print_about)
        self.dlg.show()

    @pyqtSlot()
    def run_accessibility(self):
        """Run the window for making accessibility isochrones"""
        self.dlg = OSRM_access_Dialog(iface)
        QObject.connect(
            self.dlg.originEmit,
            SIGNAL("canvasClicked(const QgsPoint&, Qt::MouseButton)"),
            self.dlg.store_origin
            )
        QObject.connect(
            self.dlg.intermediateEmit,
            SIGNAL("canvasClicked(const QgsPoint&, Qt::MouseButton)"),
            self.dlg.store_intermediate_acces
            )
        self.dlg.pushButtonOrigin.clicked.connect(self.get_origin)
        self.dlg.pushButton_about.clicked.connect(self.dlg.print_about)
        self.dlg.toolButton_poly.clicked.connect(self.polycentric)
        self.dlg.show()

    @pyqtSlot()
    def polycentric(self):
        QMessageBox.information(
                self.iface.mainWindow(), 'Info',
                "Experimental :\n\nAdd other source points and compute "
                "polycentric accessibility isochrones")
        self.get_intermediate()

    def get_origin(self):
        self.canvas.setMapTool(self.dlg.originEmit)

    def get_destination(self):
        self.canvas.setMapTool(self.dlg.destinationEmit)

    def get_intermediate(self):
        self.canvas.setMapTool(self.dlg.intermediateEmit)

# TODO :
# - ensure that the MapToolEmitPoint is unset when the plugin window is closed
# - write a function to ensure that the marker layer is in the top of the route
#    layer (in TSP dialog)
