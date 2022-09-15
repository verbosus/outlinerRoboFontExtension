import vanilla
import AppKit

from lib.tools.bezierTools import roundValue

from mojo.roboFont import OpenWindow, CurrentGlyph, CurrentFont
from mojo.extensions import getExtensionDefault, setExtensionDefault, getExtensionDefaultColor, setExtensionDefaultColor, NSColorToRgba
from mojo.subscriber import WindowController, Subscriber, registerGlyphEditorSubscriber, unregisterGlyphEditorSubscriber
from mojo.events import postEvent
from mojo.UI import CurrentSpaceCenter
from mojo.UI import getDefault, setDefault

from mojo.events import addObserver, removeObserver

import mojo.drawingTools as ctx

from defcon import Glyph, registerRepresentationFactory, unregisterRepresentationFactory

from fontTools.pens.cocoaPen import CocoaPen
from fontTools.misc.transform import Transform

from outlinePen import OutlinePen


OUTLINE_PALETTE_DEFAULT_KEY = "com.typemytype.outliner"
OUTLINE_CHANGED_EVENT_KEY = "com.typemytype.outliner.changed"
OUTLINE_DISPLAY_CHANGED_EVENT_KEY = "com.typemytype.outliner.displayChanged"


def calculate(glyph, options, preserveComponents=None):
    if preserveComponents is not None:
        options["preserveComponents"] = preserveComponents

    pen = OutlinePen(
        glyph.layer,
        offset=options["offset"],
        contrast=options["contrast"],
        contrastAngle=options["contrastAngle"],
        connection=options["connection"],
        cap=options["cap"],
        miterLimit=options["miterLimit"],
        closeOpenPaths=options["closeOpenPaths"],
        optimizeCurve=options["optimizeCurve"],
        preserveComponents=options["preserveComponents"],
        filterDoubles=options["filterDoubles"]
    )

    glyph.draw(pen)

    pen.drawSettings(
        drawOriginal=options["addOriginal"],
        drawInner=options["addInner"],
        drawOuter=options["addOuter"]
    )

    result = pen.getGlyph()
    if options["keepBounds"]:
        if glyph.bounds and result.bounds:
            minx1, miny1, maxx1, maxy1 = glyph.bounds
            minx2, miny2, maxx2, maxy2 = result.bounds

            h1 = maxy1 - miny1

            w2 = maxx2 - minx2
            h2 = maxy2 - miny2

            scale = h1 / h2
            center = minx2 + w2 * .5, miny2 + h2 * .5

            wrapped = RGlyph(result)
            wrapped.scaleBy((scale, scale), center)

    return result


class OutlinerGlyphEditor(Subscriber):

    # debug = True

    controller = None

    def build(self):
        glyphEditor = self.getGlyphEditor()
        spaceCenter = self.getSpaceCenter()
        backgroundContainer = glyphEditor.extensionContainer(
            OUTLINE_PALETTE_DEFAULT_KEY, location='background')
        previewContainer = glyphEditor.extensionContainer(
            OUTLINE_PALETTE_DEFAULT_KEY, location='preview')
        self.backgroundPath = backgroundContainer.appendPathSublayer()
        self.previewPath = previewContainer.appendPathSublayer()
        self.updateDisplay()
        self.updateOutline()

    def destroy(self):
        glyphEditor = self.getGlyphEditor()
        backgroundContainer = glyphEditor.extensionContainer(
            OUTLINE_PALETTE_DEFAULT_KEY, location='background')
        backgroundContainer.clearSublayers()
        previewContainer = glyphEditor.extensionContainer(
            OUTLINE_PALETTE_DEFAULT_KEY, location='preview')
        previewContainer.clearSublayers()

    def outlinerDidChange(self, info):
        self.updateOutline()

    def outlinerDisplayDidChanged(self, info):
        self.updateDisplay()

    def glyphEditorDidSetGlyph(self, info):
        self.updateOutline(info["glyph"])

    def glyphEditorGlyphDidChangeOutline(self, info):
        self.updateOutline(info["glyph"])
        
    def glyphEditorWillShowPreview(self, info):
        view = info['glyphEditor'].getGlyphView()
        self._currentGlyphViewPreviewFillColor = view.glyphViewPreviewFillColor
        view.glyphViewPreviewFillColor = AppKit.NSColor.clearColor()
        view.drawingBoardLayer().defaultsChanged()

    def glyphEditorWillHidePreview(self, info):
        view = info['glyphEditor'].getGlyphView()
        view.glyphViewPreviewFillColor = self._currentGlyphViewPreviewFillColor
        view.drawingBoardLayer().defaultsChanged()

    def updateDisplay(self):
        if self.controller:
            displayOptions = self.controller.getDisplayOptions()
            r, g, b, a = displayOptions["color"]
            self.backgroundPath.setVisible(displayOptions["preview"])
            with self.backgroundPath.propertyGroup():
                if displayOptions["shouldFill"]:
                    self.backgroundPath.setFillColor((r, g, b, a))
                else:
                    self.backgroundPath.setFillColor(None)

                if displayOptions["shouldStroke"]:
                    self.backgroundPath.setStrokeWidth(1)
                    self.backgroundPath.setStrokeColor((r, g, b, 1))
                else:
                    self.backgroundPath.setStrokeWidth(0)
                    self.backgroundPath.setStrokeColor(None)

    def updateOutline(self, glyph=None):
        if glyph is None:
            glyph = self.getGlyphEditor().getGlyph()

        if self.controller:
            options = self.controller.getOptions()
            displayOptions = self.controller.getDisplayOptions()
            result = calculate(
                glyph=glyph,
                options=options
            )
            self.backgroundPath.setPath(result.getRepresentation("merz.CGPath"))
            self.previewPath.setStrokeWidth(0)
            self.previewPath.setStrokeColor((1, 0, 0, 1))
            r, g, b, a = displayOptions["color"]
            self.previewPath.setFillColor((r, g, b, a))
            self.previewPath.setPath(result.getRepresentation("merz.CGPath"))
        else:
            self.backgroundPath.setPath(None)
            self.previewPath.setPath(None)
        
        # @@this was recommended by Frederik, but doesn’t actually trigger a 
        # space center repaint if glyph outlines are edited:
        # 
        # glyph.asFontParts().changed()
        # 
        # this, however, somehow seems to work as expected:
        glyph.asDefcon().postNotification(notification="Glyph.Changed")


class OutlinerPalette(WindowController):

    # debug = True

    def build(self):
        self.w = vanilla.FloatingWindow((300, 600), "Outline Palette")

        y = 5
        middle = 135
        textMiddle = middle - 27
        y += 10
        self.w._tickness = vanilla.TextBox((0, y - 3, textMiddle, 17), 'Thickness:', alignment="right")

        ticknessValue = getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.offset", 10)

        self.w.tickness = vanilla.Slider(
            (middle, y, -50, 15),
            minValue=1,
            maxValue=200,
            callback=self.parametersChanged,
            value=ticknessValue,
            sizeStyle="small"
        )
        self.w.ticknessText = vanilla.EditText(
            (-40, y, -10, 17),
            ticknessValue,
            callback=self.parametersTextChanged,
            sizeStyle="small"
        )
        y += 33
        self.w._contrast = vanilla.TextBox((0, y - 3, textMiddle, 17), 'Contrast:', alignment="right")

        contrastValue = getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.contrast", 0)

        self.w.contrast = vanilla.Slider(
            (middle, y, -50, 15),
            minValue=0,
            maxValue=200,
            callback=self.parametersChanged,
            value=contrastValue,
            sizeStyle="small"
        )
        self.w.contrastText = vanilla.EditText(
            (-40, y, -10, 17),
            contrastValue,
            callback=self.parametersTextChanged,
            sizeStyle="small"
        )
        y += 33
        self.w._contrastAngle = vanilla.TextBox((0, y - 3, textMiddle, 17), 'Contrast Angle:', alignment="right")

        contrastAngleValue = getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.contrastAngle", 0)

        self.w.contrastAngle = vanilla.Slider(
            (middle, y - 10, 30, 30),
            minValue=0,
            maxValue=360,
            callback=self.contrastAngleCallback,
            value=contrastAngleValue,
        )
        self.w.contrastAngle.getNSSlider().cell().setSliderType_(AppKit.NSCircularSlider)

        self.w.contrastAngleText = vanilla.EditText(
            (-40, y, -10, 17),
            contrastAngleValue,
            callback=self.parametersTextChanged,
            sizeStyle="small"
        )

        y += 33

        self.w._miterLimit = vanilla.TextBox((0, y - 3, textMiddle, 17), 'MiterLimit:', alignment="right")

        connectmiterLimitValue = getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.connectmiterLimit", True)

        self.w.connectmiterLimit = vanilla.CheckBox(
            (middle-22, y - 3, 20, 17),
            "",
            callback=self.connectmiterLimit,
            value=connectmiterLimitValue
        )

        miterLimitValue = getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.miterLimit", 10)

        self.w.miterLimit = vanilla.Slider(
            (middle, y, -50, 15),
            minValue=1,
            maxValue=200,
            callback=self.parametersChanged,
            value=miterLimitValue,
            sizeStyle="small"
        )
        self.w.miterLimitText = vanilla.EditText(
            (-40, y, -10, 17),
            miterLimitValue,
            callback=self.parametersTextChanged,
            sizeStyle="small"
        )

        self.w.miterLimit.enable(not connectmiterLimitValue)
        self.w.miterLimitText.enable(not connectmiterLimitValue)

        y += 30

        cornerAndCap = ["Square", "Round", "Butt"]

        self.w._corner = vanilla.TextBox((0, y, textMiddle, 17), 'Corner:', alignment="right")
        self.w.corner = vanilla.PopUpButton((middle - 2, y - 2, -48, 22), cornerAndCap, callback=self.parametersTextChanged)

        y += 30

        self.w._cap = vanilla.TextBox((0, y, textMiddle, 17), 'Cap:', alignment="right")
        useCapValue = getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.closeOpenPath", False)
        self.w.useCap = vanilla.CheckBox(
            (middle - 22, y, 20, 17),
            "",
            callback=self.useCapCallback,
            value=useCapValue
        )
        self.w.cap = vanilla.PopUpButton((middle - 2, y - 2, -48, 22), cornerAndCap, callback=self.parametersTextChanged)
        self.w.cap.enable(useCapValue)

        cornerValue = getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.corner", "Square")
        if cornerValue in cornerAndCap:
            self.w.corner.set(cornerAndCap.index(cornerValue))

        capValue = getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.cap", "Square")
        if capValue in cornerAndCap:
            self.w.cap.set(cornerAndCap.index(capValue))

        y += 33

        self.w.keepBounds = vanilla.CheckBox(
            (middle - 3, y, middle, 22),
            "Keep Bounds",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.keepBounds", False),
            callback=self.parametersTextChanged
        )
        y += 30
        self.w.optimizeCurve = vanilla.CheckBox(
            (middle - 3, y, middle, 22),
            "Optimize Curve",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.optimizeCurve", False),
            callback=self.parametersTextChanged
        )
        y += 30
        self.w.addOriginal = vanilla.CheckBox(
            (middle - 3, y, middle, 22),
            "Add Source",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.addOriginal", False),
            callback=self.parametersTextChanged
        )
        y += 30
        self.w.addInner = vanilla.CheckBox(
            (middle - 3, y, middle, 22),
            "Add Left",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.addInner", True),
            callback=self.parametersTextChanged
        )
        y += 30
        self.w.addOuter = vanilla.CheckBox(
            (middle - 3, y, middle, 22),
            "Add Right",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.addOuter", True),
            callback=self.parametersTextChanged
        )
        y += 35
        self.w.preview = vanilla.CheckBox(
            (middle - 3, y, middle, 22),
            "Preview",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.preview", True),
            callback=self.previewCallback
        )
        y += 30
        self.w.fill = vanilla.CheckBox(
            (middle - 3 + 10, y, middle, 22),
            "Fill",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.fill", False),
            callback=self.fillCallback, sizeStyle="small"
        )
        y += 25
        self.w.stroke = vanilla.CheckBox(
            (middle - 3 + 10, y, middle, 22),
            "Stroke",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.stroke", True),
            callback=self.strokeCallback, sizeStyle="small"
        )

        color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 1, 1, .8)

        self.w.color = vanilla.ColorWell(
            ((middle - 5) * 1.7, y - 33, -10, 60),
            color=getExtensionDefaultColor(f"{OUTLINE_PALETTE_DEFAULT_KEY}.color", color),
            callback=self.colorCallback
        )

        b = -135
        self.w.apply = vanilla.Button((-70, b, -10, 22), "Expand", self.expand, sizeStyle="small")
        self.w.applyNewFont = vanilla.Button((-190, b, -80, 22), "Expand Selection", self.expandSelection, sizeStyle="small")
        self.w.applySelection = vanilla.Button((-290, b, -200, 22), "Expand Font", self.expandFont, sizeStyle="small")

        b += 30
        self.w.expandInLayer = vanilla.CheckBox(
            (10, b, -10, 22),
            "Expand In Layer",
            sizeStyle="small",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.expandInLayer", False),
            callback=self.expandChangedCallback
        )
        self.w.expandLayerName = vanilla.EditText(
            (120, b, 100, 18),
            getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.expandLayerName", "outlined"),
            sizeStyle="small",
            callback=self.expandChangedCallback
        )
        self.w.expandLayerName.enable(getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.expandInLayer", False))

        b += 25
        self.w.preserveComponents = vanilla.CheckBox(
            (10, b, -10, 22),
            "Preserve Components",
            sizeStyle="small",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.preserveComponents", False),
            callback=self.parametersTextChanged
        )
        b += 25
        self.w.filterDoubles = vanilla.CheckBox(
            (10, b, -10, 22),
            "Filter Double points",
            sizeStyle="small",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.filterDoubles", True),
            callback=self.parametersTextChanged
        )
        b += 25
        self.w.previewInCurrentSpaceCenter = vanilla.CheckBox(
            (10, b, -10, 22),
            "⚠️ Preview in current Space Center (slow)",
            sizeStyle="small",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.previewInCurrentSpaceCenter", True),
            callback=self.parametersTextChanged
        )
        
        self.w.open()

    def started(self):
        OutlinerGlyphEditor.controller = self
        registerGlyphEditorSubscriber(OutlinerGlyphEditor)
        addObserver(self, "drawSpaceCenterOutline", "spaceCenterDraw")
        addObserver(self, "drawFontOverviewOutline", "glyphCellDraw")
        registerRepresentationFactory(Glyph, "outlinedPreview", self.outlinedPreviewFactory)

    def windowWillClose(self, sender):
        removeObserver(self, "spaceCenterDraw")
        removeObserver(self, "glyphCellDraw")
        unregisterGlyphEditorSubscriber(OutlinerGlyphEditor)
        unregisterRepresentationFactory(Glyph, "outlinedPreview")
        OutlinerGlyphEditor.controller = None

    def outlinedPreviewFactory(self, glyph):
        '''A factory function which creates a representation for a given glyph.'''
        options = self.getOptions()
        result = calculate(
            glyph=glyph,
            options=options
        )
        pen = CocoaPen(glyph.layer)
        result.draw(pen)
        return pen.path

    def drawPath(self, path):
        if not path: return

        displayOptions = self.getDisplayOptions()
        if not displayOptions['preview']: return
        if not displayOptions['previewInCurrentSpaceCenter']: return 

        r, g, b, a = displayOptions["color"]

        if displayOptions['shouldStroke']:
            ctx.strokeWidth(10)
            ctx.stroke(r, g, b, a)
            ctx.fill(r, g, b, 0)

        if displayOptions['shouldFill']:
            ctx.fill(r, g, b, a)

        ctx.drawPath(path)

    def drawSpaceCenterOutline(self, notification):
        S = CurrentSpaceCenter()
        if not S: return
        
        # get the current glyph
        glyph = notification['glyph']
        # get representation for glyph
        path = glyph.getRepresentation("outlinedPreview")

        ctx.save()
        self.drawPath(path)
        ctx.restore()

    def drawFontOverviewOutline(self, notification):
        glyph = notification['glyph']
        path = glyph.getRepresentation("outlinedPreview")

        # draw representation
        cell = notification['glyphCell']
        if not cell: return 

        ctx.save()
        baselineYOffset = (cell.font.info.ascender + -(cell.font.info.descender) / 2) * cell.scale
        headerHeight = 0
        if cell.shouldDrawHeader:
            headerHeight = cell.headerHeight

        baselineYTranslate = -(baselineYOffset / 2) + (headerHeight * cell.scale)
        ctx.transform(Transform(1, 0, 0, -1, cell.xOffset, cell.yOffset))
        
        ctx.translate(0, baselineYTranslate)
        ctx.scale(cell.scale)

        self.drawPath(path)
        ctx.restore()

    def getOptions(self):
        return dict(
            offset=int(self.w.tickness.get()),
            contrast=int(self.w.contrast.get()),
            contrastAngle=int(self.w.contrastAngle.get()),
            keepBounds=self.w.keepBounds.get(),
            preserveComponents=bool(self.w.preserveComponents.get()),
            filterDoubles=bool(self.w.filterDoubles.get()),
            connection=self.w.corner.getItems()[self.w.corner.get()],
            cap=self.w.cap.getItems()[self.w.cap.get()],
            closeOpenPaths=self.w.useCap.get(),
            miterLimit=int(self.w.miterLimit.get()),
            optimizeCurve=self.w.optimizeCurve.get(),
            addOriginal=self.w.addOriginal.get(),
            addInner=self.w.addInner.get(),
            addOuter=self.w.addOuter.get(),
        )

    def getDisplayOptions(self):
        return dict(
            preview=self.w.preview.get(),
            shouldFill=self.w.fill.get(),
            shouldStroke=self.w.stroke.get(),
            color=NSColorToRgba(self.w.color.get()),
            previewInCurrentSpaceCenter=bool(self.w.previewInCurrentSpaceCenter.get()),
        )

    # control callbacks

    def connectmiterLimit(self, sender):
        setExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.connectmiterLimit", sender.get())
        value = not sender.get()
        self.w.miterLimit.enable(value)
        self.w.miterLimitText.enable(value)
        self.parametersChanged()

    def useCapCallback(self, sender):
        value = sender.get()
        setExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.closeOpenPath", value)
        self.w.cap.enable(value)
        self.parametersChanged()

    def contrastAngleCallback(self, sender):
        if AppKit.NSEvent.modifierFlags() & AppKit.NSShiftKeyMask:
            value = sender.get()
            value = roundValue(value, 45)
            sender.set(value)
        self.parametersChanged()

    def expandChangedCallback(self, sender):
        expand = self.w.expandInLayer.get()
        setExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.expandInLayer", expand)
        setExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.expandLayerName", self.w.expandLayerName.get())
        self.w.expandLayerName.enable(expand)

    def parametersTextChanged(self, sender):
        value = sender.get()
        try:
            value = int(float(value))
        except ValueError:
            value = 10
            sender.set(value)

        self.w.tickness.set(int(self.w.ticknessText.get()))
        self.w.contrast.set(int(self.w.contrastText.get()))
        self.w.contrastAngle.set(int(self.w.contrastAngleText.get()))
        self.parametersChanged()

    def parametersChanged(self, sender=None, glyph=None):
        options = self.getOptions()
        if self.w.connectmiterLimit.get():
            self.w.miterLimit.set(options["offset"])

        for key, value in options.items():
            setExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.{key}", value)

        self.w.ticknessText.set(f"{options['offset']}")
        self.w.contrastText.set(f"{options['contrast']}")
        self.w.contrastAngleText.set(f"{options['contrastAngle']}")
        self.w.miterLimitText.set(f"{options['miterLimit']}")

        postEvent(OUTLINE_CHANGED_EVENT_KEY)

        S = CurrentSpaceCenter()
        if not S:
            return
        S.updateGlyphLineView()

    def displayParametersChanged(self):
        postEvent(OUTLINE_DISPLAY_CHANGED_EVENT_KEY)

    def previewCallback(self, sender):
        value = sender.get()
        self.w.fill.enable(value)
        self.w.stroke.enable(value)
        self.w.color.enable(value)
        setExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.preview", value)
        self.displayParametersChanged()

    def colorCallback(self, sender):
        setExtensionDefaultColor(f"{OUTLINE_PALETTE_DEFAULT_KEY}.color", sender.get())
        self.displayParametersChanged()

    def fillCallback(self, sender):
        setExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.fill", sender.get()),
        self.displayParametersChanged()

    def strokeCallback(self, sender):
        setExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.stroke", sender.get()),
        self.displayParametersChanged()

    # buttons callbacks

    def expand(self, sender):
        glyph = CurrentGlyph()
        preserveComponents = bool(self.w.preserveComponents.get())
        self.expandGlyph(glyph, preserveComponents)
        if not self.w.expandInLayer.get():
            self.w.preview.set(False)
            self.previewCallback(self.w.preview)

    def expandGlyph(self, glyph, preserveComponents=True):
        outline = calculate(glyph, self.getOptions(), preserveComponents)

        if self.w.expandInLayer.get():
            layerName = self.w.expandLayerName.get()
            if layerName:
                glyph = glyph.getLayer(layerName)

        glyph.prepareUndo("Outline")
        glyph.clearContours()
        outline.drawPoints(glyph.getPointPen())

        glyph.round()
        glyph.performUndo()

    def expandSelection(self, sender):
        font = CurrentFont()
        preserveComponents = bool(self.w.preserveComponents.get())
        selection = font.selection
        for glyphName in selection:
            glyph = font[glyphName]
            self.expandGlyph(glyph, preserveComponents)

    def expandFont(self, sender):
        font = CurrentFont()
        preserveComponents = bool(self.w.preserveComponents.get())
        for glyph in font:
            self.expandGlyph(glyph, preserveComponents)


OpenWindow(OutlinerPalette)
