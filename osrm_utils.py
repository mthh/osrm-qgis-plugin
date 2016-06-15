# -*- coding: utf-8 -*-
"""
osrm_utils
----------
Utilities function used for the plugin.

"""
import numpy as np
from itertools import islice
from PyQt4.QtGui import QColor, QFileDialog, QDialog, QMessageBox
from PyQt4.QtCore import QSettings, QFileInfo, Qt  #, QObject, pyqtSignal, QRunnable, QThreadPool
from qgis.core import (
    QgsGeometry, QgsPoint, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsSymbolV2, QgsMessageLog, QGis
    )
from qgis.gui import QgsEncodingFileDialog
from matplotlib.pyplot import contourf
from matplotlib.mlab import griddata
import urllib2
from .osrm_utils_extern import PolylineCodec  #, lru_cache
import json

__all__ = ['check_host', 'save_dialog', 'save_dialog_geo',
           'qgsgeom_from_mpl_collec', 'prepare_route_symbol',
           'interpolate_from_times', 'get_coords_ids', 'chunk_it',
           'pts_ref', 'TemplateOsrm',
           'decode_geom', 'fetch_table', 'decode_geom_to_pts', 'fetch_nearest',
           'make_regular_points', 'get_search_frame', 'get_isochrones_colors']

def _chain(*lists):
    for li in lists:
        for elem in li:
            yield elem


class TemplateOsrm(object):
    """
    Template class to be subclassed by each OSRM dialog class.
    It contains some methods used by the five next class.
    """
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


    @staticmethod
    def query_url(url):
        r = urllib2.urlopen(url)
        return json.loads(r.read(), strict=False)

    def print_about(self):
        mbox = QMessageBox(self.iface.mainWindow())
        mbox.setIcon(QMessageBox.Information)
        mbox.setWindowTitle('About')
        mbox.setTextFormat(Qt.RichText)
        mbox.setText(
            "<p><b>(Unofficial) OSRM plugin for qgis</b><br><br>"
            "Author: mthh, 2015<br>Licence : GNU GPL v2<br><br><br>Underlying "
            "routing engine is <a href='http://project-osrm.org'>OSRM</a>"
            "(Open Source Routing Engine) :<br>- Based on <a href='http://"
            "www.openstreetmap.org/copyright'>OpenStreetMap</a> "
            "dataset<br>- Easy to start a local instance<br>"
            "- Pretty fast engine (based on contraction hierarchies and mainly"
            " writen in C++)<br>- Mainly authored by D. Luxen and C. "
            "Vetter<br>(<a href='http://project-osrm.org'>http://project-osrm"
            ".org</a> or <a href='https://github.com/Project-OSRM/osrm"
            "-backend#references-in-publications'>on GitHub</a>)<br></p>")
        mbox.open()

    def store_origin(self, point):
        """
        Method to store a click on the QGIS canvas
        """
        if '4326' not in self.canvas.mapSettings().destinationCrs().authid():
            crsSrc = self.canvas.mapSettings().destinationCrs()
            xform = QgsCoordinateTransform(
                crsSrc, QgsCoordinateReferenceSystem(4326))
            point = xform.transform(point)
        self.origin = point
        self.canvas.unsetMapTool(self.originEmit)
        self.lineEdit_xyO.setText(str(point))


def check_host(url):
    """
    Helper function to get the hostname in desired format
    (i.e without "http://", with the port if needed
        and without the last '/')
    """
    if len(url) < 4:
        raise ValueError('Probably empty/non-valable url')
    if not ('http' in url and '//' in url) and url[-1] == '/':
        host = url[:-1]
    elif not ('http:' in url and '//' in url):
        host = url
    elif 'http://' in url[:7] and url[-1] == '/':
        host = url[7:-1]
    elif 'http://' in url[:7]:
        host = url[7:]
    else:
        host = url
    return host


def save_dialog(filtering="CSV (*.csv *.CSV)"):
    settings = QSettings()
    dirName = settings.value("/UI/lastShapefileDir")
    encode = settings.value("/UI/encoding")
    fileDialog = QgsEncodingFileDialog(
        None, "Save output csv", dirName, filtering, encode
        )
    fileDialog.setDefaultSuffix('csv')
    fileDialog.setFileMode(QFileDialog.AnyFile)
    fileDialog.setAcceptMode(QFileDialog.AcceptSave)
    fileDialog.setConfirmOverwrite(True)
    if not fileDialog.exec_() == QDialog.Accepted:
        return None, None
    files = fileDialog.selectedFiles()
    settings.setValue("/UI/lastShapefileDir",
                      QFileInfo(unicode(files[0])).absolutePath())
    return (unicode(files[0]), unicode(fileDialog.encoding()))


def save_dialog_geo(filtering="ESRI Shapefile (*.shp *.SHP)"):
    settings = QSettings()
    dirName = settings.value("/UI/lastShapefileDir")
    encode = settings.value("/UI/encoding")
    fileDialog = QgsEncodingFileDialog(
        None, "Save output ShapeFile", dirName, filtering, encode
        )
    fileDialog.setDefaultSuffix('shp')
    fileDialog.setFileMode(QFileDialog.AnyFile)
    fileDialog.setAcceptMode(QFileDialog.AcceptSave)
    fileDialog.setConfirmOverwrite(True)
    if not fileDialog.exec_() == QDialog.Accepted:
        return None, None
    files = fileDialog.selectedFiles()
    settings.setValue("/UI/lastShapefileDir",
                      QFileInfo(unicode(files[0])).absolutePath())
    return (unicode(files[0]), unicode(fileDialog.encoding()))


def prepare_route_symbol(nb_route):
    colors = ['#1f78b4', '#ffff01', '#ff7f00',
              '#fb9a99', '#b2df8a', '#e31a1c']
    p = nb_route % len(colors)
    my_symb = QgsSymbolV2.defaultSymbol(1)
    my_symb.setColor(QColor(colors[p]))
    my_symb.setWidth(1.2)
    return my_symb


def qgsgeom_from_mpl_collec(collections):
    polygons = []
    for i, polygon in enumerate(collections):
        mpoly = []
        for path in polygon.get_paths():
            path.should_simplify = False
            poly = path.to_polygons()
            if len(poly) > 0 and len(poly[0]) > 3:
                exterior = [QgsPoint(*p.tolist()) for p in poly[0]]
                holes = [[QgsPoint(*p.tolist()) for p in h]
                         for h in poly[1:] if len(h) > 3]
                if len(holes) == 1:
                    mpoly.append([exterior, holes[0]])
                elif len(holes) > 1:
                    mpoly.append([exterior] + [h for h in holes])
                else:
                    mpoly.append([exterior])

        if len(mpoly) == 1:
            polygons.append(QgsGeometry.fromPolygon(mpoly[0]))
        elif len(mpoly) > 1:
            polygons.append(QgsGeometry.fromMultiPolygon(mpoly))
        else:
            polygons.append(QgsGeometry.fromPolygon([]))
    return polygons


def interpolate_from_times(times, coords, levels, rev_coords=False):
    if not rev_coords:
        x = coords[..., 0]
        y = coords[..., 1]
    else:
        x = coords[..., 1]
        y = coords[..., 0]
    xi = np.linspace(np.nanmin(x), np.nanmax(x), 200)
    yi = np.linspace(np.nanmin(y), np.nanmax(y), 200)
    zi = griddata(x, y, times, xi, yi, interp='linear')
    v_bnd = np.nanmax(abs(zi))
    collec_poly = contourf(
        xi, yi, zi, levels, vmax=v_bnd, vmin=-v_bnd)
    return collec_poly


def get_coords_ids(layer, field, on_selected=False):
    if on_selected:
        get_features_method = layer.selectedFeatures
    else:
        get_features_method = layer.getFeatures

    if '4326' not in layer.crs().authid():
        xform = QgsCoordinateTransform(
            layer.crs(), QgsCoordinateReferenceSystem(4326))
        coords = [xform.transform(ft.geometry().asPoint())
                  for ft in get_features_method()]
    else:
        coords = [ft.geometry().asPoint() for ft in get_features_method()]

    if field != '':
        ids = [ft.attribute(field) for ft in get_features_method()]
    else:
        ids = [ft.id() for ft in get_features_method()]

    return coords, ids


def chunk_it(it, size):
    it = iter(it)
    return list(iter(lambda: tuple(islice(it, size)), ()))


def pts_ref(features):
    return [i[3] for i in features]


def decode_geom(encoded_polyline):
    """
    Function decoding an encoded polyline (with 'encoded polyline
    algorithme') and returning a QgsGeometry object

    Params:

    encoded_polyline: str
        The encoded string to decode
    """
    return QgsGeometry.fromPolyline(
        [QgsPoint(i[1], i[0]) for i
         in PolylineCodec().decode(encoded_polyline)])


def fetch_table(url, coords_src, coords_dest):
    """
    Function wrapping OSRM 'table' function in order to get a matrix of
    time distance as a numpy array

    Params :
        - url, str: the start of the url to use
            (containing the host and the profile version/name)

        - coords_src, list: a python list of (x, y) coordinates to use
            (they will be used a "sources" if destinations coordinates are
             provided, otherwise they will be used as source and destination
             in order to build a "square"/"symetrical" matrix)

        - coords_dest, list or None: a python list of (x, y) coordinates to use
            (if set to None, only the sources coordinates will be used in order
            to build a "square"/"symetrical" matrix)

    Output:
        - a numpy array containing the time in tenth of seconds
            (where 2147483647 means not-found route)

        - a list of "snapped" source coordinates

        - a list of "snapped" destination coordinates
            (or None if no destination coordinates where provided)
    """
    if not coords_dest:
        query = ''.join([url,
                        ';'.join([','.join([str(coord[0]), str(coord[1])]) for coord in coords_src])])
    else:
        src_end = len(coords_src)
        dest_end = src_end + len(coords_dest)
        query = ''.join([
            url,
            ';'.join([','.join([str(coord[0]), str(coord[1])]) for coord in _chain(coords_src, coords_dest)]),
            '?sources=',
            ';'.join([str(i) for i in range(src_end)]),
            '&destinations=',
            ';'.join([str(j) for j in range(src_end, dest_end)])
            ])

    try:
        res = urllib2.urlopen(query)
        parsed_json = json.loads(res.read(), strict=False)
        assert parsed_json["code"] == "Ok"
        assert "durations" in parsed_json

    except AssertionError as er:
        raise ValueError('Error while contacting OSRM instance : \n{}'
                                  .format(er))
    except Exception as err:
        raise ValueError('Error while contacting OSRM instance : \n{}'
                                  .format(err))

    durations = np.array(parsed_json["durations"], dtype=float)
    new_src_coords = [ft["location"] for ft in parsed_json["sources"]]
    new_dest_coords = None if not coords_dest \
        else [ft["location"] for ft in parsed_json["destinations"]]

    return durations, new_src_coords, new_dest_coords


def decode_geom_to_pts(encoded_polyline):
    """
    Params:

    encoded_polyline: str
        The encoded string to decode
    """
    return [(i[1], i[0]) for i in PolylineCodec().decode(encoded_polyline)]


def fetch_nearest(host, profile, coord):
    """
    Useless function wrapping OSRM 'locate' function,
    returning the reponse in JSON.
    More useless since newer version of OSRM doesn't include 'locate' function
    anymore.

    Parameters
    ----------
    coord: list/tuple of two floats
        (x ,y) where x is longitude and y is latitude
    host: str, like 'localhost:5000'
        Url and port of the OSRM instance (no final bakslash)

    Return
    ------
       The coordinates returned by OSRM (or False if any error is encountered)
    """
    url = ''.join(['http://', host, '/nearest/',
                   profile, '/', str(coord[0]), ',', str(coord[1])])
    try:  # Querying the OSRM instance
        rep = urllib2.urlopen(url)
        parsed_json = json.loads(rep.read(), strict=False)
    except Exception as err:
        print(err)
        return False
    if not 'code' in parsed_json or not "Ok" in parsed_json['code']:
        return False
    else:
        return parsed_json["waypoints"][0]["location"]


def make_regular_points(bounds, nb_pts):
    """
    Return a square grid of regular points (same number in height and width
    even if the bbox is not a square).
    """
    xmin, ymin, xmax, ymax = bounds
    nb_h = int(round(np.sqrt(nb_pts)))
    prog_x = [xmin + i * ((xmax - xmin) / nb_h) for i in range(nb_h + 1)]
    prog_y = [ymin + i * ((ymax - ymin) / nb_h) for i in range(nb_h + 1)]
    result = []
    for x in prog_x:
        for y in prog_y:
            result.append((x, y))
    return result


def get_search_frame(point, max_time):
    """
    Define the search frame (ie. the bbox), given a center point and
    the maximum time requested

    Return
    ------
    xmin, ymin, xmax, ymax : float
    """
    search_len = (max_time * 4) * 1000
    crsSrc = QgsCoordinateReferenceSystem(4326)
    xform = QgsCoordinateTransform(crsSrc, QgsCoordinateReferenceSystem(3857))
    point = xform.transform(QgsPoint(*point))
    xmin = point[0] - search_len
    ymin = point[1] - search_len
    xmax = point[0] + search_len
    ymax = point[1] + search_len
    crsSrc = QgsCoordinateReferenceSystem(3857)
    xform = QgsCoordinateTransform(crsSrc, QgsCoordinateReferenceSystem(4326))
    xmin, ymin = xform.transform(QgsPoint(xmin, ymin))
    xmax, ymax = xform.transform(QgsPoint(xmax, ymax))
    return xmin, ymin, xmax, ymax


def get_isochrones_colors(nb_features):
    """ Ugly "helper" function to rewrite to avoid repetitions """
    return {1: ('#a6d96a',),
            2: ('#fee08b', '#a6d96a'),
            3: ('#66bd63',
                '#fee08b', '#f46d43'),
            4: ('#1a9850', '#a6d96a',
                '#fee08b', '#f46d43'),
            5: ('#1a9850', '#66bd63',
                '#ffffbf', '#fc8d59', '#d73027'),
            6: ('#1a9850', '#66bd63', '#d9ef8b',
                '#fee08b', '#fc8d59', '#d73027'),
            7: ('#1a9850', '#66bd63', '#d9ef8b', '#ffffbf',
                '#fee08b', '#fc8d59', '#d73027'),
            8: ('#1a9850', '#66bd63', '#a6d96a', '#d9ef8b',
                '#fee08b', '#fdae61', '#f46d43', '#d73027'),
            9: ('#1a9850', '#66bd63', '#a6d96a', '#d9ef8b', '#ffffbf',
                '#fee08b', '#fdae61', '#f46d43', '#d73027'),
            10: ('#006837', '#1a9850', '#66bd63', '#a6d96a', '#d9ef8b',
                 '#fee08b', '#fdae61', '#f46d43', '#d73027', '#a50026'),
            11: ('#006837', '#1a9850', '#66bd63', '#a6d96a', '#d9ef8b',
                 '#ffffbf', '#fee08b', '#fdae61', '#f46d43', '#d73027',
                 '#a50026'),
            12: ('#006837', '#1a9850', '#66bd63', '#a6d96a', '#d9ef8b',
                 '#e7ef88', '#ffffbf', '#fee08b', '#fdae61', '#f46d43',
                 '#d73027', '#a50026'),
            13: ('#006837', '#1a9850', '#66bd63', '#a6d96a', '#d9ef8b',
                 '#e7ef88', '#ffffbf', '#fee08b', '#fdae61', '#f46d43',
                 '#d73027', '#bb2921', '#a50026'),
            14: ('#006837', '#1a9850', '#66bd63', '#a6d96a', '#d9ef8b',
                 '#e7ef88', '#ffffbf', '#fff6a0', '#fee08b', '#fdae61',
                 '#f46d43', '#d73027', '#bb2921', '#a50026'),
            15: ('#006837', '#1a9850', '#66bd63', '#a6d96a', '#d9ef8b',
                 '#e7ef88', '#ffffbf', '#ffffbf', '#fff6a0', '#fee08b',
                 '#fdae61', '#f46d43', '#d73027', '#bb2921', '#a50026'),
            16: ('#006837', '#1a9850', '#66bd63', '#a6d96a',
                 '#d9ef8b', '#e7ef88', '#ffffbf', '#ffffbf', '#ffffbf',
                 '#fff6a0', '#fee08b', '#fdae61', '#f46d43', '#d73027',
                 '#bb2921', '#a50026'),
            }[nb_features]
