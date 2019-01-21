# coding: utf-8
# /*##########################################################################
#
# Copyright (c) 2017-2019 European Synchrotron Radiation Facility
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
# ###########################################################################*/
"""
Module containing widgets displaying stats from items of a plot.
"""

__authors__ = ["H. Payno"]
__license__ = "MIT"
__date__ = "24/07/2018"


from collections import OrderedDict
from contextlib import contextmanager
import logging
import weakref

import numpy

from silx.gui import qt
from silx.gui import icons
from silx.gui.plot import stats as statsmdl
from silx.gui.widgets.TableWidget import TableWidget
from silx.gui.plot.stats.statshandler import StatsHandler, StatFormatter

from . import PlotWidget
from . import items as plotitems
from ..plot3d.SceneWidget import SceneWidget
from ..plot3d import items as plot3ditems


_logger = logging.getLogger(__name__)


class StatsTable(TableWidget):
    """
    TableWidget displaying for each curves contained by the Plot some
    information:

    * legend
    * minimal value
    * maximal value
    * standard deviation (std)

    :param QWidget parent: The widget's parent.
    :param Union[PlotWidget,SceneWidget] plot:
        :class:`PlotWidget` or :class:`SceneWidget` instance on which to operate
    """

    COMPATIBLE_ITEMS = tuple(
        item for items in statsmdl.BASIC_COMPATIBLE_KINDS.values() for item in items)

    _LEGEND_HEADER_DATA = 'legend'
    _KIND_HEADER_DATA = 'kind'

    def __init__(self, parent=None, plot=None):
        TableWidget.__init__(self, parent)
        self._plotRef = None
        self._displayOnlyActItem = False
        self._statsOnVisibleData = False
        self._statsHandler = None

        # Init for _displayOnlyActItem == False
        self.setSelectionBehavior(qt.QAbstractItemView.SelectRows)
        self.setSelectionMode(qt.QAbstractItemView.SingleSelection)
        self.currentItemChanged.connect(self._currentItemChanged)

        self.setRowCount(0)
        self.setColumnCount(2)

        # Init headers
        headerItem = qt.QTableWidgetItem('Legend')
        headerItem.setData(qt.Qt.UserRole, self._LEGEND_HEADER_DATA)
        self.setHorizontalHeaderItem(0, headerItem)
        headerItem = qt.QTableWidgetItem('Kind')
        headerItem.setData(qt.Qt.UserRole, self._KIND_HEADER_DATA)
        self.setHorizontalHeaderItem(1, headerItem)

        self.setSortingEnabled(True)
        self.setPlot(plot)

    @contextmanager
    def _disableSorting(self):
        """Context manager that disables table sorting

        Previous state is restored when leaving
        """
        sorting = self.isSortingEnabled()
        if sorting:
            self.setSortingEnabled(False)
        yield
        if sorting:
            self.setSortingEnabled(sorting)

    def setStats(self, statsHandler):
        """Set which stats to display and the associated formatting.

        :param StatsHandler statsHandler:
            Set the statistics to be displayed and how to format them using
        """
        if statsHandler is None:
            statsHandler = StatsHandler(statFormatters=())
        elif isinstance(statsHandler, (list, tuple)):
            statsHandler = StatsHandler(statsHandler)
        assert isinstance(statsHandler, StatsHandler)

        self._removeAllItems()

        self._statsHandler = statsHandler

        self.setRowCount(0)
        self.setColumnCount(len(statsHandler.stats) + 2)  # + legend and kind

        for index, stat in enumerate(self._statsHandler.stats.values()):
            headerItem = qt.QTableWidgetItem(stat.name.capitalize())
            headerItem.setData(qt.Qt.UserRole, stat.name)
            if stat.description is not None:
                headerItem.setToolTip(stat.description)
            self.setHorizontalHeaderItem(2 + index, headerItem)

        horizontalHeader = self.horizontalHeader()
        if hasattr(horizontalHeader, 'setSectionResizeMode'):  # Qt5
            horizontalHeader.setSectionResizeMode(qt.QHeaderView.ResizeToContents)
        else:  # Qt4
            horizontalHeader.setResizeMode(qt.QHeaderView.ResizeToContents)

        self._updateItemObserve()

    def getStatsHandler(self):
        """Returns the :class:`StatsHandler` in use.

        :rtype: StatsHandler
        """
        return self._statsHandler

    @staticmethod
    def _getKind(item):
        """Returns the kind of item

        :param item:
        :rtype: str
        """
        for kind, types in statsmdl.BASIC_COMPATIBLE_KINDS.items():
            if isinstance(item, types):
                return kind
        return None

    def setPlot(self, plot):
        """Define the plot to interact with

        :param Union[PlotWidget,SceneWidget,None] plot:
            The plot containing the items on which statistics are applied
        """
        assert plot is None or isinstance(plot, (PlotWidget, SceneWidget))
        self._dealWithPlotConnection(create=False)
        self._removeAllItems()
        self._plotRef = None if plot is None else weakref.ref(plot)
        self._dealWithPlotConnection(create=True)
        self._updateItemObserve()

    def getPlot(self):
        """Returns the plot attached to this widget

        :rtype: Union[PlotWidget,SceneWidget,None]
        """
        return None if self._plotRef is None else self._plotRef()

    def _updateItemObserve(self):
        """Reload table depending on mode"""
        plot = self.getPlot()  # can be None

        self._removeAllItems()

        # Get selected or all items from the plot
        items = []
        if self._displayOnlyActItem:  # Only selected
            if isinstance(plot, PlotWidget):
                for kind in PlotWidget._ACTIVE_ITEM_KINDS:
                    item = plot._getActiveItem(kind=kind)
                    if item is not None:
                        items.append(item)
            elif isinstance(plot, SceneWidget):
                items = [plot.selection().getCurrentItem()]

        else:  # All items
            if isinstance(plot, PlotWidget):
                items = plot._getItems()
            elif isinstance(plot, SceneWidget):
                items = plot.getItems()

        # Add items to the plot
        for item in items:
            if isinstance(item, self.COMPATIBLE_ITEMS):
                self._addItem(item)

    def _dealWithPlotConnection(self, create=True):
        """Manage connection to plot signals

        Note: connection on Item are managed by the _removeItem function
        """
        plot = self.getPlot()
        if plot is None:
            return

        # Prepare list of (signal, slot) to connect/disconnect
        connections = []
        if isinstance(plot, PlotWidget):
            connections.append((plot.sigPlotSignal, self._zoomPlotChanged))
            if self._displayOnlyActItem:
                connections += [
                    (plot.sigActiveCurveChanged, self._plotCurrentChanged),
                    (plot.sigActiveImageChanged, self._plotCurrentChanged),
                    (plot.sigActiveScatterChanged, self._plotCurrentChanged)]
            else:
                connections += [
                    (plot.sigItemAdded, self._plotItemAdded),
                    (plot.sigItemAboutToBeRemoved, self._plotItemRemoved)]

                # Handle sync of table selection with current curve
                connections += [
                    (plot.sigActiveCurveChanged, self._plot2dActiveCurveChanged),
                    (plot.sigActiveImageChanged, self._plot2dActiveImageChanged),
                    (plot.sigActiveScatterChanged, self._plot2dActiveScatterChanged)]

        elif isinstance(plot, SceneWidget):
            if self._displayOnlyActItem:
                selection = plot.selection()
                connections.append(
                    (selection.sigCurrentChanged, self._plotCurrentChanged))
            else:
                scene = plot.getSceneGroup()
                connections += [
                    (scene.sigItemAdded, self._plotItemAdded),
                    (scene.sigItemRemoved, self._plotItemRemoved)]
                connections.append((plot.selection().sigCurrentChanged,
                                    self._plot3dCurrentChanged))

        for signal, slot in connections:
            if create:
                signal.connect(slot)
            else:
                signal.disconnect(slot)

    def _itemToRow(self, item):
        """Find the row corresponding to a plot item

        :param item: The plot item
        :return: The corresponding row index
        :rtype: Union[int,None]
        """
        for row in range(self.rowCount()):
            tableItem = self.item(row, 0)
            if tableItem.data(qt.Qt.UserRole) == item:
                return row
        return None

    def _itemToTableItems(self, item):
        """Find all table items corresponding to a plot item

        :param item: The plot item
        :return: An ordered dict of column name to QTableWidgetItem mapping
            for the given plot item.
        :rtype: OrderedDict
        """
        result = OrderedDict()
        row = self._itemToRow(item)
        if row is not None:
            for column in range(self.columnCount()):
                tableItem = self.item(row, column)
                if tableItem.data(qt.Qt.UserRole) != item:
                    _logger.error("Table item/plot item mismatch")
                else:
                    header = self.horizontalHeaderItem(column)
                    name = header.data(qt.Qt.UserRole)
                    result[name] = tableItem
        return result

    def _plotItemChanged(self, event):
        """Handle modifications of the items.

        :param event:
        """
        item = self.sender()
        self._updateStats(item)

    def _addItem(self, item):
        """Add a plot item to the table

        :param item: The plot item
        """
        if self._itemToRow(item) is not None:
            _logger.error("Item already present in the table")
            self._updateStats(item)
            return

        kind = self._getKind(item)
        if kind is None:
            _logger.error("Item has not a supported type: %s", item)
            return

        # Prepare table items
        tableItems = [
            qt.QTableWidgetItem(),  # Legend
            qt.QTableWidgetItem()]  # Kind

        for column in range(2, self.columnCount()):
            header = self.horizontalHeaderItem(column)
            name = header.data(qt.Qt.UserRole)

            formatter = self._statsHandler.formatters[name]
            if formatter:
                tableItem = formatter.tabWidgetItemClass()
            else:
                tableItem = qt.QTableWidgetItem()

            tooltip = self._statsHandler.stats[name].getToolTip(kind=kind)
            if tooltip is not None:
                tableItem.setToolTip(tooltip)

            tableItems.append(tableItem)

        # Disable sorting while adding table items
        with self._disableSorting():
            # Add a row to the table
            self.setRowCount(self.rowCount() + 1)

            # Add table items to the last row
            row = self.rowCount() - 1
            for column, tableItem in enumerate(tableItems):
                tableItem.setData(qt.Qt.UserRole, item)
                tableItem.setFlags(
                    qt.Qt.ItemIsEnabled | qt.Qt.ItemIsSelectable)
                self.setItem(row, column, tableItem)

            # Update table items content
            self._updateStats(item)

        # Listen for item changes
        # Using queued connection to avoid issue with sender
        # being that of the signal calling the signal
        item.sigItemChanged.connect(self._plotItemChanged,
                                    qt.Qt.QueuedConnection)

    def _removeItem(self, item):
        """Remove table items corresponding to given plot item from the table.

        :param item: The plot item
        """
        row = self._itemToRow(item)
        if row is None:
            _logger.error("Removing item that is not in table: %s", str(item))
            return
        item.sigItemChanged.disconnect(self._plotItemChanged)
        self.removeRow(row)

    def _removeAllItems(self):
        """Remove content of the table"""
        for row in range(self.rowCount()):
            tableItem = self.item(row, 0)
            item = tableItem.data(qt.Qt.UserRole)
            item.sigItemChanged.disconnect(self._plotItemChanged)
        self.clearContents()
        self.setRowCount(0)

    def _updateStats(self, item):
        """Update displayed information for given plot item

        :param item: The plot item
        """
        plot = self.getPlot()
        if plot is None:
            _logger.info("Plot not available")
            return

        row = self._itemToRow(item)
        if row is None:
            _logger.error("This item is not in the table: %s", str(item))
            return

        statsHandler = self.getStatsHandler()
        if statsHandler is not None:
            stats = statsHandler.calculate(
                item, plot, self._statsOnVisibleData)
        else:
            stats = {}

        with self._disableSorting():
            for name, tableItem in self._itemToTableItems(item).items():
                if name == self._LEGEND_HEADER_DATA:
                    if isinstance(item, plotitems.Item):
                        text = item.getLegend()
                    elif isinstance(item, plot3ditems.Item3D):
                        text = item.getLabel()
                    else:
                        _logger.error("Item not supported: %s", str(item))
                        text = '-'
                    tableItem.setText(text)
                elif name == self._KIND_HEADER_DATA:
                    tableItem.setText(self._getKind(item))
                else:
                    value = stats.get(name)
                    if value is None:
                        _logger.error("Value not found for: %s", name)
                        tableItem.setText('-')
                    else:
                        tableItem.setText(str(value))

    def _updateAllStats(self):
        """Update stats for all rows in the table"""
        with self._disableSorting():
            for row in range(self.rowCount()):
                tableItem = self.item(row, 0)
                item = tableItem.data(qt.Qt.UserRole)
                self._updateStats(item)

    def _currentItemChanged(self, current, previous):
        """Handle change of selection in table and sync plot selection

        :param QTableWidgetItem current:
        :param QTableWidgetItem previous:
        """
        if current and current.row() >= 0:
            plot = self.getPlot()
            if isinstance(plot, PlotWidget):
                item = current.data(qt.Qt.UserRole)
                kind = self._getKind(item)
                if kind in PlotWidget._ACTIVE_ITEM_KINDS:
                    if plot._getActiveItem(kind) != item:
                        plot._setActiveItem(kind, item.getLegend())
            elif isinstance(plot, SceneWidget):
                item = current.data(qt.Qt.UserRole)
                plot.selection().setCurrentItem(item)

    def setDisplayOnlyActiveItem(self, displayOnlyActItem):
        """Toggle display off all items or only the active/selected one

        :param bool displayOnlyActItem:
            True if we want to only show active item
        """
        if self._displayOnlyActItem == displayOnlyActItem:
            return
        self._dealWithPlotConnection(create=False)
        if not self._displayOnlyActItem:
            self.currentItemChanged.disconnect(self._currentItemChanged)

        self._displayOnlyActItem = displayOnlyActItem

        self._updateItemObserve()
        self._dealWithPlotConnection(create=True)

        if not self._displayOnlyActItem:
            self.currentItemChanged.connect(self._currentItemChanged)
            self.setSelectionMode(qt.QAbstractItemView.SingleSelection)
        else:
            self.setSelectionMode(qt.QAbstractItemView.NoSelection)

    def setStatsOnVisibleData(self, b):
        """Toggle computation of statistics on whole data or only visible ones.

        .. warning:: When visible data is activated we will process to a simple
                     filtering of visible data by the user. The filtering is a
                     simple data sub-sampling. No interpolation is made to fit
                     data to boundaries.

        :param bool b: True if we want to apply statistics only on visible data
        """
        if self._statsOnVisibleData != b:
            self._statsOnVisibleData = b
            self._updateAllStats()

    def _plotCurrentChanged(self, *args, **kwargs):
        """Update change of selected items"""
        if self._displayOnlyActItem:
            self._updateItemObserve()

    def _plotItemAdded(self, item):
        """Handles new items in the plot

        :param item: New plot item
        """
        if isinstance(item, self.COMPATIBLE_ITEMS):
            self._addItem(item)

    def _plotItemRemoved(self, item):
        """Handles removal of an item from the plot

        :param item: Plot item being removed
        """
        if isinstance(item, self.COMPATIBLE_ITEMS):
            self._removeItem(item)

    def _zoomPlotChanged(self, event):
        """Handle zoom change."""
        if self._statsOnVisibleData and event['event'] == 'limitsChanged':
                self._updateAllStats()

    # SceneWidget specific slot

    def _plot3dCurrentChanged(self, current, previous):
        """Handle change of selection in a :class:`SceneWidget`

        :param Item3D current:
        :param Item3D previous:
        """
        plot = self.getPlot()
        if isinstance(plot, SceneWidget):
            row = self._itemToRow(current)
            if row is None:
                if self.currentRow() >= 0:
                    self.setCurrentCell(-1, -1)
            else:
                if row != self.currentRow():
                    self.setCurrentCell(row, 0)

            plot.selection().setCurrentItem(current)

    # PlotWidget specific slots

    def _plot2dActiveItemChanged(self, kind):
        """Generic plot active item management.

        :param str kind:
        """
        plot = self.getPlot()
        if isinstance(plot, PlotWidget):
            item = plot._getActiveItem(kind=kind)
            if item is not None:
                row = self._itemToRow(item)
                if row != self.currentRow():
                    self.setCurrentCell(row, 0)
            else:
                if self.currentRow() >= 0:
                    self.setCurrentCell(-1, -1)

    def _plot2dActiveCurveChanged(self, previous, current):
        """Handle update of active curve"""
        self._plot2dActiveItemChanged(kind='curve')

    def _plot2dActiveImageChanged(self, previous, current):
        """Handle update of active image"""
        self._plot2dActiveItemChanged(kind='image')

    def _plot2dActiveScatterChanged(self, previous, current):
        """Handle update of active scatter"""
        self._plot2dActiveItemChanged(kind='scatter')


class _OptionsWidget(qt.QToolBar):

    def __init__(self, parent=None):
        qt.QToolBar.__init__(self, parent)
        self.setIconSize(qt.QSize(16, 16))

        action = qt.QAction(self)
        action.setIcon(icons.getQIcon("stats-active-items"))
        action.setText("Active items only")
        action.setToolTip("Display stats for active items only.")
        action.setCheckable(True)
        action.setChecked(True)
        self.__displayActiveItems = action

        action = qt.QAction(self)
        action.setIcon(icons.getQIcon("stats-whole-items"))
        action.setText("All items")
        action.setToolTip("Display stats for all available items.")
        action.setCheckable(True)
        self.__displayWholeItems = action

        action = qt.QAction(self)
        action.setIcon(icons.getQIcon("stats-visible-data"))
        action.setText("Use the visible data range")
        action.setToolTip("Use the visible data range.<br/>"
                          "If activated the data is filtered to only use"
                          "visible data of the plot."
                          "The filtering is a data sub-sampling."
                          "No interpolation is made to fit data to"
                          "boundaries.")
        action.setCheckable(True)
        self.__useVisibleData = action

        action = qt.QAction(self)
        action.setIcon(icons.getQIcon("stats-whole-data"))
        action.setText("Use the full data range")
        action.setToolTip("Use the full data range.")
        action.setCheckable(True)
        action.setChecked(True)
        self.__useWholeData = action

        self.addAction(self.__displayWholeItems)
        self.addAction(self.__displayActiveItems)
        self.addSeparator()
        self.addAction(self.__useVisibleData)
        self.addAction(self.__useWholeData)

        self.itemSelection = qt.QActionGroup(self)
        self.itemSelection.setExclusive(True)
        self.itemSelection.addAction(self.__displayActiveItems)
        self.itemSelection.addAction(self.__displayWholeItems)

        self.dataRangeSelection = qt.QActionGroup(self)
        self.dataRangeSelection.setExclusive(True)
        self.dataRangeSelection.addAction(self.__useWholeData)
        self.dataRangeSelection.addAction(self.__useVisibleData)

    def isActiveItemMode(self):
        return self.itemSelection.checkedAction() is self.__displayActiveItems

    def isVisibleDataRangeMode(self):
        return self.dataRangeSelection.checkedAction() is self.__useVisibleData


class StatsWidget(qt.QWidget):
    """
    Widget displaying a set of :class:`Stat` to be displayed on a
    :class:`StatsTable` and to be apply on items contained in the :class:`Plot`
    Also contains options to:

    * compute statistics on all the data or on visible data only
    * show statistics of all items or only the active one

    :param QWidget parent: Qt parent
    :param Union[PlotWidget,SceneWidget] plot:
        The plot containing items on which we want statistics.
    :param StatsHandler stats:
        Set the statistics to be displayed and how to format them using
    """

    sigVisibilityChanged = qt.Signal(bool)
    """Signal emitted when the visibility of this widget changes.

    It Provides the visibility of the widget.
    """

    NUMBER_FORMAT = '{0:.3f}'

    def __init__(self, parent=None, plot=None, stats=None):
        qt.QWidget.__init__(self, parent)
        self.setLayout(qt.QVBoxLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)
        self._options = _OptionsWidget(parent=self)
        self.layout().addWidget(self._options)
        self._statsTable = StatsTable(parent=self, plot=plot)
        self.setStats(stats)

        self.layout().addWidget(self._statsTable)

        self._options.itemSelection.triggered.connect(
            self._optSelectionChanged)
        self._options.dataRangeSelection.triggered.connect(
            self._optDataRangeChanged)
        self._optSelectionChanged()
        self._optDataRangeChanged()

    def getStatsTable(self):
        """Returns the :class:`StatsTable` used by this widget.

        :rtype: StatsTable
        """
        return self._statsTable

    def showEvent(self, event):
        self.sigVisibilityChanged.emit(True)
        qt.QWidget.showEvent(self, event)

    def hideEvent(self, event):
        self.sigVisibilityChanged.emit(False)
        qt.QWidget.hideEvent(self, event)

    def _optSelectionChanged(self, action=None):
        self.getStatsTable().setDisplayOnlyActiveItem(
            self._options.isActiveItemMode())

    def _optDataRangeChanged(self, action=None):
        self.getStatsTable().setStatsOnVisibleData(
            self._options.isVisibleDataRangeMode())

    # Proxy methods

    def setStats(self, statsHandler):
        return self.getStatsTable().setStats(statsHandler=statsHandler)

    setStats.__doc__ = StatsTable.setStats.__doc__

    def setPlot(self, plot):
        return self.getStatsTable().setPlot(plot=plot)

    setPlot.__doc__ = StatsTable.setPlot.__doc__

    def getPlot(self):
        return self.getStatsTable().getPlot()

    getPlot.__doc__ = StatsTable.getPlot.__doc__

    def setDisplayOnlyActiveItem(self, displayOnlyActItem):
        return self.getStatsTable().setDisplayOnlyActiveItem(
            displayOnlyActItem=displayOnlyActItem)

    setDisplayOnlyActiveItem.__doc__ = StatsTable.setDisplayOnlyActiveItem.__doc__

    def setStatsOnVisibleData(self, b):
        return self.getStatsTable().setStatsOnVisibleData(b=b)

    setStatsOnVisibleData.__doc__ = StatsTable.setStatsOnVisibleData.__doc__


class BasicStatsWidget(StatsWidget):
    """
    Widget defining a simple set of :class:`Stat` to be displayed on a
    :class:`StatsWidget`.

    :param QWidget parent: Qt parent
    :param PlotWidget plot:
        The plot containing items on which we want statistics.
    """

    STATS = StatsHandler((
        (statsmdl.StatMin(), StatFormatter()),
        statsmdl.StatCoordMin(),
        (statsmdl.StatMax(), StatFormatter()),
        statsmdl.StatCoordMax(),
        (('std', numpy.std), StatFormatter()),
        (('mean', numpy.mean), StatFormatter()),
        statsmdl.StatCOM()
    ))

    def __init__(self, parent=None, plot=None):
        StatsWidget.__init__(self, parent=parent, plot=plot, stats=self.STATS)
