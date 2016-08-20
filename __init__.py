# -*- coding: utf-8 -*-
"""
/***************************************************************************
 OSRM
                                 A QGIS plugin
 Find a route with OSRM
                             -------------------
        begin                : 2015-09-29
        copyright            : (C) 2015 by mthh
        email                : mthh@#!.org
        git sha              : $Format:%H$
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
 This script initializes the plugin, making it known to QGIS.
"""


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load OSRM class from file OSRM.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    #
    from .osrm import OSRM
    return OSRM(iface)
