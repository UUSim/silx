# coding: utf-8
# /*##########################################################################
#
# Copyright (c) 2018 European Synchrotron Radiation Facility
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
"""This module profile tools for scatter plots.
"""

__authors__ = ["T. Vincent"]
__license__ = "MIT"
__date__ = "30/05/2018"


import logging
import time
import weakref

import numpy
from scipy.interpolate import LinearNDInterpolator

from ....utils.weakref import WeakMethodProxy
from ... import qt, icons, colors
from .. import PlotWidget, items
from ..ProfileMainWindow import ProfileMainWindow
from .roi import RegionOfInterestManager


_logger = logging.getLogger(__name__)


# TODO log scale?
# TODO move profile window creation outside and add a sigProfileChanged(title, x, y)

class _BaseProfileToolBar(qt.QToolBar):
    """Base class for QToolBar plot profiling tools

    :param parent: See :class:`QToolBar`.
    :param plot: :class:`PlotWindow` instance on which to operate.
    :param str title: See :class:`QToolBar`.
    """

    sigProfileChanged = qt.Signal()
    """Signal emitted when the profile has changed"""

    def __init__(self, parent=None, plot=None, title=''):
        super(_BaseProfileToolBar, self).__init__(title, parent)

        self.__nPoints = 1024
        self.__profile = None
        self.__profileTitle = ''

        assert isinstance(plot, PlotWidget)
        self._plotRef = weakref.ref(
            plot, WeakMethodProxy(self.__plotDestroyed))

        self._profilePlotRef = None
        self._profileMainWindow = None

        # Set-up interaction manager
        roiManager = RegionOfInterestManager(plot)
        self._roiManagerRef = weakref.ref(roiManager)

        roiManager.sigInteractionModeFinished.connect(
            self.__interactionFinished)
        roiManager.sigRegionOfInterestChanged.connect(self.updateProfile)
        roiManager.sigRegionOfInterestAdded.connect(self.__roiAdded)

        # Add interactive mode actions
        for kind, icon in (
                ('hline', 'shape-horizontal'),
                ('vline', 'shape-vertical'),
                ('line', 'shape-diagonal')):
            action = roiManager.getInteractionModeAction(kind)
            action.setIcon(icons.getQIcon(icon))
            self.addAction(action)

        # Add clear action
        action = qt.QAction(icons.getQIcon('profile-clear'),
                            'Clear Profile', self)
        action.setToolTip('Clear the profile Region of interest')
        action.setCheckable(False)
        action.triggered.connect(self.clearProfile)
        self.addAction(action)

        # Initialize color
        self._color = None
        self.setColor('red')

        # Listen to plot limits changed
        plot.getXAxis().sigLimitsChanged.connect(self.updateProfile)
        plot.getYAxis().sigLimitsChanged.connect(self.updateProfile)

        # Listen to plot scale
        plot.getXAxis().sigScaleChanged.connect(self.__plotAxisScaleChanged)
        plot.getYAxis().sigScaleChanged.connect(self.__plotAxisScaleChanged)

    def getProfileData(self, copy=True):
        """Returns the profile data as (x, y) or None

        :rtype: Union[List[numpy.ndarray],None]
        """
        if self.__profile is None:
            return None
        else:
            return (numpy.array(self.__profile[0], copy=copy),
                    numpy.array(self.__profile[1], copy=copy))

    def getProfileTitle(self):
        """Returns the profile title

        :rtype: str
        """
        return self.__profileTitle

    # Handle plot reference

    def __plotDestroyed(self, ref):
        """Handle finalization of PlotWidget

        :param ref: weakref to the plot
        """
        self._plotRef = None
        self.setEnabled(False)  # Profile is pointless
        for action in self.actions():  # TODO useful?
            self.removeAction(action)

    def getPlotWidget(self):
        """The :class:`.PlotWidget` associated to the toolbar.

        :rtype: Union[PlotWidget,None]
        """
        return None if self._plotRef is None else self._plotRef()

    def _getRoiManager(self):
        """Returns the used ROI manager

        :rtype: RegionOfInterestManager
        """
        return self._roiManagerRef()

    # Profile Plot

    def getProfilePlot(self):
        """Returns the plot displaying profiles.

        :rtype: PlotWidget
        """
        if self._profilePlotRef is None:
            if self._profileMainWindow is None:
                self._profileMainWindow = ProfileMainWindow(self)
                self._profileMainWindow.sigClose.connect(self.clearProfile)

            self._profilePlotRef = weakref.ref(
                self._profileMainWindow.getPlot())

        return self._profilePlotRef()

    def setProfilePlot(self, plot):
        """Set the plot to use to display profiles.

        :param PlotWidget plot
        """
        self._profilePlotRef = None if plot is None else weakref.ref(plot)
        self.updateProfile()

    def _showProfileMainWindow(self):
        """If profile window was created by this toolbar,
        try to avoid overlapping with the toolbar's parent window.
        """
        self.getProfilePlot()  # This creates _profileMainWindow if needed
        if (self._profileMainWindow is not None and
                not self._profileMainWindow.isVisible()):
            self._profileMainWindow.show()
            self._profileMainWindow.raise_()

            window = self.window()
            winGeom = window.frameGeometry()
            qapp = qt.QApplication.instance()
            desktop = qapp.desktop()
            screenGeom = desktop.availableGeometry(self)
            spaceOnLeftSide = winGeom.left()
            spaceOnRightSide = screenGeom.width() - winGeom.right()

            frameGeometry = self._profileMainWindow.frameGeometry()
            profileWindowWidth = frameGeometry.width()
            if (profileWindowWidth < spaceOnRightSide):
                # Place profile on the right
                self._profileMainWindow.move(winGeom.right(), winGeom.top())
            elif(profileWindowWidth < spaceOnLeftSide):
                # Place profile on the left
                self._profileMainWindow.move(
                    max(0, winGeom.left() - profileWindowWidth), winGeom.top())

    # Handle plot in log scale

    def __plotAxisScaleChanged(self, scale):
        """Handle change of axis scale in the plot widget"""
        plot = self.getPlotWidget()
        if plot is None:
            return

        xScale = plot.getXAxis().getScale()
        yScale = plot.getYAxis().getScale()

        if xScale == items.Axis.LINEAR and yScale == items.Axis.LINEAR:
            self.setEnabled(True)
            self.updateProfile()

        else:
            self.setEnabled(False)
            self.clearProfile()

            roiManager = self._getRoiManager()
            if roiManager is not None:
                roiManager.stop()  # Stop interactive mode

    # Profile color

    def getColor(self):
        """Returns the color used for the profile and ROI

        :rtype: QColor
        """
        return qt.QColor.fromRgbF(*self._color)

    def setColor(self, color):
        """Set the color to use for ROI and profile.

        :param color:
           Either a color name, a QColor, a list of uint8 or float in [0, 1].
        """
        self._color = colors.rgba(color)
        roiManager = self._getRoiManager()
        if roiManager is not None:
            roiManager.setColor(self._color)
            for roi in roiManager.getRegionOfInterests():
                roi.setColor(self._color)
        self.updateProfile()

    # Number of points

    def getNPoints(self):
        """Returns the number of points of the profiles

        :rtype: int
        """
        return self.__nPoints

    def setNPoints(self, npoints):
        """Set the number of points of the profiles

        :param int npoints:
        """
        npoints = int(npoints)
        if npoints < 1:
            raise ValueError("Unsupported number of points: %d" % npoints)
        else:
            self.__nPoints = npoints

    # Handle ROI manager

    def __interactionFinished(self, rois):
        """Handle end of interactive mode"""
        self.clearProfile()

        if self._profileMainWindow is not None:
            self._profileMainWindow.hide()

    def __roiAdded(self, roi):
        """Handle new ROI"""
        roi.setLabel('Profile')
        roi.setEditable(True)

        # Remove any other ROI
        roiManager = self._getRoiManager()
        if roiManager is not None:
            for regionOfInterest in list(roiManager.getRegionOfInterests()):
                if regionOfInterest is not roi:
                    roiManager.removeRegionOfInterest(regionOfInterest)

    def computeProfile(self, points):
        """Compute corresponding profile

        Override in subclass to compute profile

        :param numpy.ndarray points: (N, 2) points coordinates
        :return: y profile data or None
        """
        return None

    def computeProfileTitle(self, x0, y0, x1, y1):
        """Compute corresponding plot title

        This can be overridden to change title behavior.

        :param float x0: Profile start point X coord
        :param float y0: Profile start point Y coord
        :param float x1: Profile end point X coord
        :param float y1: Profile end point X coord
        :return: Title to use
        :rtype: str
        """
        if x0 == x1:
            title = 'X = %g; Y = [%g, %g]' % (x0, y0, y1)
        elif y0 == y1:
            title = 'Y = %g; X = [%g, %g]' % (y0, x0, x1)
        else:
            m = (y1 - y0) / (x1 - x0)
            b = y0 - m * x0
            title = 'Y = %g * X %+g' % (m, b)

        return title

    def updateProfile(self, *args):
        """Update profile according to ROI"""
        roiManager = self._getRoiManager()
        if roiManager is None:
            roi = None
        else:
            rois = roiManager.getRegionOfInterests()
            roi = None if len(rois) == 0 else rois[0]

        profilePlot = self.getProfilePlot()
        if profilePlot is None:
            return

        # Reset profile plot
        profilePlot.clear()
        profilePlot.setGraphTitle('')

        if roi is None:
            return

        kind = roi.getKind()
        if kind not in ('hline', 'vline', 'line'):  # Never event
            _logger.warning('Unhandled ROI added')
            return

        # Get end points
        if kind == 'line':
            points = roi.getControlPoints()
            x0, y0 = points[0]
            x1, y1 = points[1]

        elif kind in ('hline', 'vline'):
            plot = self.getPlotWidget()
            if plot is None:
                return

            if kind == 'hline':
                x0, x1 = plot.getXAxis().getLimits()
                y0 = y1 = roi.getControlPoints()[0, 1]

            elif kind == 'vline':
                x0 = x1 = roi.getControlPoints()[0, 0]
                y0, y1 = plot.getYAxis().getLimits()

        else:
            _logger.error('Unsupported kind: {}'.format(kind))
            return

        if x1 < x0 or (x1 == x0 and y1 < y0):
            # Invert points
            x0, y0, x1, y1 = x1, y1, x0, y0

        # Update plot
        self.__profileTitle = self.computeProfileTitle(x0, y0, x1, y1)
        profilePlot.setGraphTitle(self.__profileTitle)

        nPoints = self.getNPoints()

        profilePoints = numpy.transpose((
            numpy.linspace(x0, x1, nPoints, endpoint=True),
            numpy.linspace(y0, y1, nPoints, endpoint=True)))

        if numpy.abs(x1 - x0) > numpy.abs(y1 - y0):
            profilePlot.setGraphXLabel('X')
            xProfile = profilePoints[:, 0]
        else:
            profilePlot.setGraphXLabel('Y')
            xProfile = profilePoints[:, 1]

        yProfile = self.computeProfile(profilePoints)

        if yProfile is None:
            self.__profile = None

        else:
            self.__profile = xProfile, yProfile
            profilePlot.addCurve(
                xProfile, yProfile, legend='Profile', color=self._color)

        self.sigProfileChanged.emit()

        self._showProfileMainWindow()

    def clearProfile(self):
        """Clear the current line ROI and associated profile"""
        roiManager = self._getRoiManager()
        if roiManager is not None:
            roiManager.clearRegionOfInterests()


class _InterpolatorInitThread(qt.QThread):
    """Thread building a scatter interpolator

    :param QObject parent: See QObject
    """

    def __init__(self, parent=None):
        super(_InterpolatorInitThread, self).__init__(parent)
        self._points = None
        self._values = None
        self._interpolator = None

    def getData(self):
        """Returns points and values used to initialise the interpolator

        :rtype: List[numpy.ndarray]
        """
        return self._points, self._values

    def getInterpolator(self):
        """Returns the initialised interpolator

        :rtype: Union[LinearNDInterpolator,None]
        """
        return self._interpolator

    def start(self, points, values, priority=qt.QThread.InheritPriority):
        """Start the thread.

        :param numpy.ndarray points: Point coordinates (N, D)
        :param numpy.ndarray values: Values the N points (1D array)
        :param priority: Priority hint see :meth:QThread.start` for details
        :return:
        """
        self._points = points
        self._values = values
        super(_InterpolatorInitThread, self).start(priority)

    def run(self):
        """Run the init of the scatter interpolator"""
        startTime = time.time()

        self._interpolator = None
        try:
            interpolator = LinearNDInterpolator(self._points,
                                                self._values)
        except:
            _logger.warning(
                "Cannot initialise scatter profile interpolator")

        else:
            # First call takes a while, do it here
            interpolator([(0., 0.)])

            self._interpolator = interpolator
            _logger.info("Interpolator initialised in %f s",
                         (time.time() - startTime))


class ScatterProfileToolBar(_BaseProfileToolBar):
    """QToolBar providing scatter plot profiling tools

    :param parent: See :class:`QToolBar`.
    :param plot: :class:`PlotWindow` instance on which to operate.
    :param str title: See :class:`QToolBar`.
    """

    def __init__(self, parent=None, plot=None, title='Scatter Profile'):
        super(ScatterProfileToolBar, self).__init__(parent, plot, title)
        self.__interpolator = None
        self.__interpolatorCache = None  # points, values, interpolator
        self.__initThread = None

        roiManager = self._getRoiManager()
        if roiManager is None:
            _logger.error(
                "Error during scatter profile toolbar initialisation")
        else:
            roiManager.sigInteractionModeStarted.connect(
                self.__interactionStarted)
            roiManager.sigInteractionModeFinished.connect(
                self.__interactionFinished)
            if roiManager.isStarted():
                self.__interactionStarted(roiManager.getRegionOfInterestKind())

    def __interactionStarted(self, kind):
        """Handle start of ROI interaction"""
        plot = self.getPlotWidget()
        if plot is None:
            return

        plot.sigActiveScatterChanged.connect(self.__activeScatterChanged)

        scatter = plot._getActiveItem(kind='scatter')
        legend = None if scatter is None else scatter.getLegend()
        self.__activeScatterChanged(None, legend)

    def __interactionFinished(self, rois):
        """Handle end of ROI interaction"""
        self.__stopInitThread()

        plot = self.getPlotWidget()
        if plot is None:
            return

        plot.sigActiveScatterChanged.disconnect(self.__activeScatterChanged)

        scatter = plot._getActiveItem(kind='scatter')
        legend = None if scatter is None else scatter.getLegend()
        self.__activeScatterChanged(legend, None)

    def __activeScatterChanged(self, previous, legend):
        """Handle change of active scatter

        :param Union[str,None] previous:
        :param Union[str,None] legend:
        """
        self.__stopInitThread()

        # Reset interpolator
        self.__interpolator = None

        plot = self.getPlotWidget()
        if plot is None:
            _logger.error("Associated PlotWidget no longer exists")

        else:
            if previous is not None:  # Disconnect signal
                scatter = plot.getScatter(previous)
                if scatter is not None:
                    scatter.sigItemChanged.disconnect(
                        self.__scatterItemChanged)

            if legend is not None:
                scatter = plot.getScatter(legend)
                if scatter is None:
                    _logger.error("Cannot retrieve active scatter")

                else:
                    scatter.sigItemChanged.connect(self.__scatterItemChanged)

                    points = numpy.transpose(numpy.array((
                        scatter.getXData(copy=False),
                        scatter.getYData(copy=False))))
                    values = scatter.getValueData(copy=False)

                    # Check interpolator cache
                    if (self.__interpolatorCache is not None and
                            len(points) == len(self.__interpolatorCache[0]) and
                            numpy.all(numpy.equal(self.__interpolatorCache[0], points)) and
                            numpy.all(numpy.equal(self.__interpolatorCache[1], values))):
                        # Reuse previous interpolator
                        _logger.info(
                            'Active scatter change: Reuse interpolator')
                        self.__interpolator = self.__interpolatorCache[2]

                    else:
                        # Interpolator needs update: Start background processing
                        _logger.info(
                            'Active scatter changed: Rebuild interpolator')
                        self.__interpolator = None
                        self.__interpolatorCache = None
                        self.__initThread = _InterpolatorInitThread(self)
                        self.__initThread.finished.connect(
                            self.__initThreadFinished)
                        self.__initThread.start(points, values)

        # Refresh profile
        self.updateProfile()

    def __scatterItemChanged(self, event):
        """Handle update of active scatter plot item

        :param ItemChangedType event:
        """
        if event == items.ItemChangedType.DATA:
            scatter = self.sender()
            if scatter is None:
                _logger.error("Cannot retrieve updated scatter item")

            else:
                self.__stopInitThread()

                points = numpy.transpose(numpy.array((
                    scatter.getXData(copy=False),
                    scatter.getYData(copy=False))))
                values = scatter.getValueData(copy=False)

                if (self.__interpolatorCache is not None and
                        len(points) == len(self.__interpolatorCache[0]) and
                        numpy.all(numpy.equal(self.__interpolatorCache[0], points)) and
                        numpy.all(numpy.equal(self.__interpolatorCache[1], values))):
                    # Reuse previous interpolator
                    _logger.info(
                        'Scatter changed: Reuse previous interpolator')
                    self.__interpolator = self.__interpolatorCache[2]

                else:
                    # Interpolator needs update: Start background processing
                    _logger.info(
                        'Scatter changed: Rebuild interpolator')
                    self.__interpolator = None
                    self.__interpolatorCache = None
                    self.__initThread = _InterpolatorInitThread(self)
                    self.__initThread.finished.connect(
                        self.__initThreadFinished)
                    self.__initThread.start(points, values)

    # Handle interpolator init thread

    def __stopInitThread(self):
        """Terminates any interpolator initialisation thread"""
        if self.__initThread is not None:
            _logger.info('Terminate init thread')
            self.__initThread.finished.disconnect(self.__initThreadFinished)
            # Leads to errors: self.__initThread.terminate()
            self.__initThread = None

    def __initThreadFinished(self):
        """Handle end of init interpolator thread"""
        if self.__initThread is not None:
            self.__interpolator = self.__initThread.getInterpolator()
            points, values = self.__initThread.getData()
            self.__interpolatorCache = points, values, self.__interpolator
            self.__initThread = None
            self.updateProfile()

    # Overridden methods
    def computeProfileTitle(self, x0, y0, x1, y1):
        """Compute corresponding plot title

        :param float x0: Profile start point X coord
        :param float y0: Profile start point Y coord
        :param float x1: Profile end point X coord
        :param float y1: Profile end point X coord
        :return: Title to use
        :rtype: str
        """
        if self.__initThread is not None:
            return 'Pre-processing data...'

        else:
            return super(ScatterProfileToolBar, self).computeProfileTitle(
                x0, y0, x1, y1)

    def computeProfile(self, points):
        """Compute corresponding profile

        :param numpy.ndarray points: (N, 2) points coordinates
        :return: y profile data
        """
        if self.__interpolator is None:
            return None

        yProfile = self.__interpolator(points)

        if not numpy.any(numpy.isfinite(yProfile)):
            # Profile is outside convex hull
            return None

        return yProfile
