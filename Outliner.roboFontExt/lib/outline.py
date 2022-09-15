import AppKit
import vanilla

from fontTools.pens.cocoaPen import CocoaPen
from fontTools.misc.transform import Transform

from defcon import Glyph, registerRepresentationFactory, unregisterRepresentationFactory

from lib.tools.bezierTools import roundValue

from mojo.roboFont import OpenWindow, CurrentGlyph, CurrentFont
from mojo.extensions import getExtensionDefault, setExtensionDefault, getExtensionDefaultColor, setExtensionDefaultColor, NSColorToRgba
from mojo.subscriber import WindowController, Subscriber, registerGlyphEditorSubscriber, unregisterGlyphEditorSubscriber
from mojo.events import postEvent, addObserver, removeObserver

from mojo.UI import CurrentSpaceCenter
from mojo.UI import getDefault, setDefault
from mojo.UI import AccordionView

import mojo.drawingTools as ctx

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
        self.w = vanilla.FloatingWindow((300, 300), "Outliner", minSize=(300, 73))

        y = 5
        middle = 135
        textMiddle = middle - 27
        y += 10

        self.outlineGroup = vanilla.Group((0, 0, -0, -0))
        self.previewGroup = vanilla.Group((0, 0, -0, -0))
        self.expandGroup  = vanilla.Group((0, 0, -0, -0))

        self.outlineGroup._thickness = vanilla.TextBox((0, y - 3, textMiddle, 17), 'Thickness:', alignment="right")

        thicknessValue = getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.offset", 10)

        self.outlineGroup.thickness = vanilla.Slider(
            (middle, y, -50, 15),
            minValue=1,
            maxValue=200,
            callback=self.parametersChanged,
            value=thicknessValue,
            sizeStyle="small"
        )
        self.outlineGroup.thicknessText = vanilla.EditText(
            (-40, y, -10, 17),
            thicknessValue,
            callback=self.parametersTextChanged,
            sizeStyle="small"
        )
        y += 33
        self.outlineGroup._contrast = vanilla.TextBox((0, y - 3, textMiddle, 17), 'Contrast:', alignment="right")

        contrastValue = getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.contrast", 0)

        self.outlineGroup.contrast = vanilla.Slider(
            (middle, y, -50, 15),
            minValue=0,
            maxValue=200,
            callback=self.parametersChanged,
            value=contrastValue,
            sizeStyle="small"
        )
        self.outlineGroup.contrastText = vanilla.EditText(
            (-40, y, -10, 17),
            contrastValue,
            callback=self.parametersTextChanged,
            sizeStyle="small"
        )
        y += 33
        self.outlineGroup._contrastAngle = vanilla.TextBox((0, y - 3, textMiddle, 17), 'Contrast Angle:', alignment="right")

        contrastAngleValue = getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.contrastAngle", 0)

        self.outlineGroup.contrastAngle = vanilla.Slider(
            (middle, y - 10, 30, 30),
            minValue=0,
            maxValue=360,
            callback=self.contrastAngleCallback,
            value=contrastAngleValue,
        )
        self.outlineGroup.contrastAngle.getNSSlider().cell().setSliderType_(AppKit.NSCircularSlider)

        self.outlineGroup.contrastAngleText = vanilla.EditText(
            (-40, y, -10, 17),
            contrastAngleValue,
            callback=self.parametersTextChanged,
            sizeStyle="small"
        )

        y += 33

        self.outlineGroup._miterLimit = vanilla.TextBox((0, y - 3, textMiddle, 17), 'Miter Limit:', alignment="right")

        connectmiterLimitValue = getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.connectmiterLimit", True)

        self.outlineGroup.connectmiterLimit = vanilla.CheckBox(
            (middle-22, y - 3, 20, 17),
            "",
            callback=self.connectmiterLimit,
            value=connectmiterLimitValue
        )

        miterLimitValue = getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.miterLimit", 10)

        self.outlineGroup.miterLimit = vanilla.Slider(
            (middle, y, -50, 15),
            minValue=1,
            maxValue=200,
            callback=self.parametersChanged,
            value=miterLimitValue,
            sizeStyle="small"
        )
        self.outlineGroup.miterLimitText = vanilla.EditText(
            (-40, y, -10, 17),
            miterLimitValue,
            callback=self.parametersTextChanged,
            sizeStyle="small"
        )

        self.outlineGroup.miterLimit.enable(not connectmiterLimitValue)
        self.outlineGroup.miterLimitText.enable(not connectmiterLimitValue)

        y += 30

        cornerAndCap = ["Square", "Round", "Butt"]

        self.outlineGroup._corner = vanilla.TextBox((0, y, textMiddle, 17), 'Corner:', alignment="right")
        self.outlineGroup.corner = vanilla.PopUpButton((middle - 2, y - 2, -48, 22), cornerAndCap, callback=self.parametersTextChanged)

        y += 30

        self.outlineGroup._cap = vanilla.TextBox((0, y, textMiddle, 17), 'Cap:', alignment="right")
        useCapValue = getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.closeOpenPath", False)
        self.outlineGroup.useCap = vanilla.CheckBox(
            (middle - 22, y, 20, 17),
            "",
            callback=self.useCapCallback,
            value=useCapValue
        )
        self.outlineGroup.cap = vanilla.PopUpButton((middle - 2, y - 2, -48, 22), cornerAndCap, callback=self.parametersTextChanged)
        self.outlineGroup.cap.enable(useCapValue)

        cornerValue = getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.corner", "Square")
        if cornerValue in cornerAndCap:
            self.outlineGroup.corner.set(cornerAndCap.index(cornerValue))

        capValue = getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.cap", "Square")
        if capValue in cornerAndCap:
            self.outlineGroup.cap.set(cornerAndCap.index(capValue))

        y += 33

        self.outlineGroup.keepBounds = vanilla.CheckBox(
            (middle - 3, y, middle, 22),
            "Keep Bounds",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.keepBounds", False),
            callback=self.parametersTextChanged
        )
        y += 30
        self.outlineGroup.optimizeCurve = vanilla.CheckBox(
            (middle - 3, y, middle, 22),
            "Optimize Curve",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.optimizeCurve", False),
            callback=self.parametersTextChanged
        )
        y += 30
        self.outlineGroup.addOriginal = vanilla.CheckBox(
            (middle - 3, y, middle, 22),
            "Add Source",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.addOriginal", False),
            callback=self.parametersTextChanged
        )
        y += 30
        self.outlineGroup.addInner = vanilla.CheckBox(
            (middle - 3, y, middle, 22),
            "Add Left",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.addInner", True),
            callback=self.parametersTextChanged
        )
        y += 30
        self.outlineGroup.addOuter = vanilla.CheckBox(
            (middle - 3, y, middle, 22),
            "Add Right",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.addOuter", True),
            callback=self.parametersTextChanged
        )
        
        y = 0
        self.previewGroup.preview = vanilla.CheckBox(
            (middle - 3, y, middle, 22),
            "Preview",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.preview", True),
            callback=self.previewCallback
        )
        y += 30
        self.previewGroup.fill = vanilla.CheckBox(
            (middle - 3 + 10, y, middle, 22),
            "Fill",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.fill", False),
            callback=self.fillCallback, sizeStyle="small"
        )
        y += 25
        self.previewGroup.stroke = vanilla.CheckBox(
            (middle - 3 + 10, y, middle, 22),
            "Stroke",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.stroke", True),
            callback=self.strokeCallback, sizeStyle="small"
        )

        color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 1, 1, .8)

        self.previewGroup.color = vanilla.ColorWell(
            ((middle - 5) * 1.7, y - 33, -10, 60),
            color=getExtensionDefaultColor(f"{OUTLINE_PALETTE_DEFAULT_KEY}.color", color),
            callback=self.colorCallback
        )

        b = 0
        self.expandGroup.expandInLayer = vanilla.CheckBox(
            (120, b, -10, 22),
            "Expand In Layer",
            sizeStyle="small",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.expandInLayer", False),
            callback=self.expandChangedCallback
        )
        self.expandGroup.expandLayerName = vanilla.EditText(
            (240, b, 100, 18),
            getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.expandLayerName", "outlined"),
            sizeStyle="small",
            callback=self.expandChangedCallback
        )
        self.expandGroup.expandLayerName.enable(getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.expandInLayer", False))

        b += 25
        self.expandGroup.preserveComponents = vanilla.CheckBox(
            (120, b, -10, 22),
            "Preserve Components",
            sizeStyle="small",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.preserveComponents", False),
            callback=self.parametersTextChanged
        )
        b += 25
        self.expandGroup.filterDoubles = vanilla.CheckBox(
            (120, b, -10, 22),
            "Filter Double points",
            sizeStyle="small",
            value=getExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.filterDoubles", True),
            callback=self.parametersTextChanged
        )
        b += 30

        self.expandGroup.applySelection = vanilla.Button((120, b, 80, 22), "Expand Font", self.expandFont, sizeStyle="small")
        self.expandGroup.applyNewFont = vanilla.Button((200, b, 120, 22), "Expand Selection", self.expandSelection, sizeStyle="small")
        self.expandGroup.apply = vanilla.Button((320, b, 60, 22), "Expand", self.expand, sizeStyle="small")

        
        descriptions = [
            dict(label="Outline parameters", view=self.outlineGroup, size=370, collapsed=False, canResize=False),
            dict(label="Preview", view=self.previewGroup, size=90, collapsed=True, canResize=False),
            dict(label="Expand", view=self.expandGroup, size=140, collapsed=True, canResize=False),
        ]
        self.w.accordionView = AccordionView((0, 0, -0, -0), descriptions)
        
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
            offset=int(self.outlineGroup.thickness.get()),
            contrast=int(self.outlineGroup.contrast.get()),
            contrastAngle=int(self.outlineGroup.contrastAngle.get()),
            keepBounds=self.outlineGroup.keepBounds.get(),
            preserveComponents=bool(self.expandGroup.preserveComponents.get()),
            filterDoubles=bool(self.expandGroup.filterDoubles.get()),
            connection=self.outlineGroup.corner.getItems()[self.outlineGroup.corner.get()],
            cap=self.outlineGroup.cap.getItems()[self.outlineGroup.cap.get()],
            closeOpenPaths=self.outlineGroup.useCap.get(),
            miterLimit=int(self.outlineGroup.miterLimit.get()),
            optimizeCurve=self.outlineGroup.optimizeCurve.get(),
            addOriginal=self.outlineGroup.addOriginal.get(),
            addInner=self.outlineGroup.addInner.get(),
            addOuter=self.outlineGroup.addOuter.get(),
        )

    def getDisplayOptions(self):
        return dict(
            preview=self.previewGroup.preview.get(),
            shouldFill=self.previewGroup.fill.get(),
            shouldStroke=self.previewGroup.stroke.get(),
            color=NSColorToRgba(self.previewGroup.color.get()),
        )

    # control callbacks

    def connectmiterLimit(self, sender):
        setExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.connectmiterLimit", sender.get())
        value = not sender.get()
        self.outlineGroup.miterLimit.enable(value)
        self.outlineGroup.miterLimitText.enable(value)
        self.parametersChanged()

    def useCapCallback(self, sender):
        value = sender.get()
        setExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.closeOpenPath", value)
        self.outlineGroup.cap.enable(value)
        self.parametersChanged()

    def contrastAngleCallback(self, sender):
        if AppKit.NSEvent.modifierFlags() & AppKit.NSShiftKeyMask:
            value = sender.get()
            value = roundValue(value, 45)
            sender.set(value)
        self.parametersChanged()

    def expandChangedCallback(self, sender):
        expand = self.expandGroup.expandInLayer.get()
        setExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.expandInLayer", expand)
        setExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.expandLayerName", self.expandGroup.expandLayerName.get())
        self.expandGroup.expandLayerName.enable(expand)

    def parametersTextChanged(self, sender):
        value = sender.get()
        try:
            value = int(float(value))
        except ValueError:
            value = 10
            sender.set(value)

        self.outlineGroup.thickness.set(int(self.outlineGroup.thicknessText.get()))
        self.outlineGroup.contrast.set(int(self.outlineGroup.contrastText.get()))
        self.outlineGroup.contrastAngle.set(int(self.outlineGroup.contrastAngleText.get()))
        self.parametersChanged()

    def parametersChanged(self, sender=None, glyph=None):
        options = self.getOptions()
        if self.outlineGroup.connectmiterLimit.get():
            self.outlineGroup.miterLimit.set(options["offset"])

        for key, value in options.items():
            setExtensionDefault(f"{OUTLINE_PALETTE_DEFAULT_KEY}.{key}", value)

        self.outlineGroup.thicknessText.set(f"{options['offset']}")
        self.outlineGroup.contrastText.set(f"{options['contrast']}")
        self.outlineGroup.contrastAngleText.set(f"{options['contrastAngle']}")
        self.outlineGroup.miterLimitText.set(f"{options['miterLimit']}")

        postEvent(OUTLINE_CHANGED_EVENT_KEY)

        S = CurrentSpaceCenter()
        if not S:
            return
        S.updateGlyphLineView()

    def displayParametersChanged(self):
        postEvent(OUTLINE_DISPLAY_CHANGED_EVENT_KEY)

    def previewCallback(self, sender):
        value = sender.get()
        self.previewGroup.fill.enable(value)
        self.previewGroup.stroke.enable(value)
        self.previewGroup.color.enable(value)
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
        preserveComponents = bool(self.expandGroup.preserveComponents.get())
        self.expandGlyph(glyph, preserveComponents)
        if not self.expandGroup.expandInLayer.get():
            self.previewGroup.preview.set(False)
            self.previewCallback(self.previewGroup.preview)

    def expandGlyph(self, glyph, preserveComponents=True):
        outline = calculate(glyph, self.getOptions(), preserveComponents)

        if self.expandGroup.expandInLayer.get():
            layerName = self.expandGroup.expandLayerName.get()
            if layerName:
                glyph = glyph.getLayer(layerName)

        glyph.prepareUndo("Outline")
        glyph.clearContours()
        outline.drawPoints(glyph.getPointPen())

        glyph.round()
        glyph.performUndo()

    def expandSelection(self, sender):
        font = CurrentFont()
        preserveComponents = bool(self.expandGroup.preserveComponents.get())
        selection = font.selection
        for glyphName in selection:
            glyph = font[glyphName]
            self.expandGlyph(glyph, preserveComponents)

    def expandFont(self, sender):
        font = CurrentFont()
        preserveComponents = bool(self.expandGroup.preserveComponents.get())
        for glyph in font:
            self.expandGlyph(glyph, preserveComponents)


OpenWindow(OutlinerPalette)
