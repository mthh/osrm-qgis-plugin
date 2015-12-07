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
        # Set up the user interface from Designer.
        # After setupUI you can access any designer object by doing
        # self.<objectname>, and you can use autoconnect slots - see
        # http://qt-project.org/doc/qt-4.8/designer-using-a-ui-file.html
        # #widgets-and-dialogs-with-auto-connect
        self.setupUi(self)


class OSRM_table_Dialog(QtGui.QDialog, FORM_CLASS_t):
    def __init__(self, parent=None):
        """Constructor."""
        super(OSRM_table_Dialog, self).__init__(parent)
        self.setupUi(self)


class OSRM_access_Dialog(QtGui.QDialog, FORM_CLASS_a):
    def __init__(self, parent=None):
        """Constructor."""
        super(OSRM_access_Dialog, self).__init__(parent)
        self.setupUi(self)


class OSRM_batch_route_Dialog(QtGui.QDialog, FORM_CLASS_b):
    def __init__(self, parent=None):
        """Constructor."""
        super(OSRM_batch_route_Dialog, self).__init__(parent)
        self.setupUi(self)
