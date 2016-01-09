.. OSRM documentation master file, created by
   sphinx-quickstart on Sun Feb 12 17:11:03 2012.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to OSRM's documentation!
============================================

Contents:

.. toctree::
   :maxdepth: 2

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

Overview
========
Tiny QGIS plug-in allowing to retrieve and display data from an (ideally locally based) `OSRM`_ web service.

This plug-in is in its early stage of development and the code is hosted `on github`_.

Current version : 0.0.1-rc1

Functionality 
=============
- Find a route
- Get a time matrix
- Make accessibility isochrones
- Compute and export many routes

Usage
=====
This plug-in is primarily aimed to be used on a local instance of OSRM.

If used to request the public API you have to adhere to the `API Usage Policy`_ (which include no heavy usage, like )

Example
=======
Display a simple route from OSRM (with support of viapoints, alternatives roads and route instructions):

.. image:: img/route.jpg
   :scale: 33 %
   :alt: route illustration
   :align: center

Get a time matrix from a (or two) QGIS point layer(s) :

.. image:: img/table.jpg
   :scale: 33 %
   :alt: isochrone illustration
   :align: center

Compute monocentric or polycentric accessibility isochrones: 

.. image:: img/multi_isochrone.jpg
   :scale: 33 %
   :alt: isochrone illustration
   :align: center

Retrieve many routes between two QGIS layer of points:

.. image:: img/many_routes.jpg
   :scale: 33 %
   :alt: isochrone illustration
   :align: center


Changelog
=========

	- Add support for intermediate points in viaroute displaying
	- Add experimental support for "polycentric" accessibility isochrones
	- Add support for new OSRM rectangular matrix (and isochrones creation using it)
0.0.1:
	- First release
0.0.1-rc1:
	- Drop the use of shapely for isochrone polygons construction.
	- ADD: a backport of functools.lru_cache to cache http request on client side.
	- ADD: restriction on the batch viaroute to prevent a massive use of the public API.

.. _API Usage Policy: https://github.com/Project-OSRM/osrm-backend/wiki/Api-usage-policy
.. _OSRM: http://project-osrm.org/
.. _on github: https://mthh.github.com/osrm-qgis-plugin/

