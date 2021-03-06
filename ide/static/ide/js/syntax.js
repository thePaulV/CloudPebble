CloudPebble.Editor.PebbleMode = {
    name: 'clike',
    useCPP: true,
    keywords: {
        // C
        'auto': true,
        'if': true,
        'break': true,
        'int': true,
        'case': true,
        'long': true,
        'char': true,
        'register': true,
        'continue': true,
        'return': true,
        'default': true,
        'short': true,
        'do': true,
        'sizeof': true,
        'double': true,
        'static': true,
        'else': true,
        'struct': true,
        'entry': true,
        'switch': true,
        'extern': true,
        'typedef': true,
        'float': true,
        'union': true,
        'for': true,
        'unsigned': true,
        'goto': true,
        'while': true,
        'enum': true,
        'void': true,
        'const': true,
        'signed': true,
        'volatile': true,
        'bool': true,
        '_Bool': true,
        'int8_t': true,
        'uint8_t': true,
        'int16_t': true,
        'uint16_t': true,
        'int32_t': true,
        'uint32_t': true,
        'time_t': true,
        // Pebble-specific
        'Animation': true,
        'AnimationCurve': true,
        'AnimationHandlers': true,
        'AnimationImplementation': true,
        'AnimationSetupImplementation': true,
        'AnimationStartedHandler': true,
        'AnimationStoppedHandler': true,
        'AnimationTeardownImplementation': true,
        'AnimationTimingFunction': true,
        'AnimationUpdateImplementation': true,
        'AppContextRef': true,
        'AppTaskContextRef': true,
        'AppTimerHandle': true,
        'BmpContainer': true,
        'ButtonId': true,
        'ClickConfig': true,
        'ClickConfigProvider': true,
        'ClickHandler': true,
        'ClickRecognizerRef': true,
        'GAlign': true,
        'GBitmap': true,
        'GColor': true,
        'GCompOp': true,
        'GContext': true,
        'GCornerMask': true,
        'GPath': true,
        'GPathInfo': true,
        'GPoint': true,
        'GRect': true,
        'GSize': true,
        'GTextAlignment': true,
        'GTextLayoutCacheRef': true,
        'GTextOverflowMode': true,
        'Layer': true,
        'LayerUpdateProc': true,
        'PblTm': true,
        'PebbleAppButtonEventHandler': true,
        'PebbleAppDeinitEventHandler': true,
        'PebbleAppHandlers': true,
        'PebbleAppInitEventHandler': true,
        'PebbleAppInputHandlers': true,
        'PebbleAppRenderEventHandler': true,
        'PebbleAppTickEventHandler': true,
        'PebbleAppTickInfo': true,
        'PebbleAppTimerEventHandler': true,
        'PebbleButtonEvent': true,
        'PebbleCallbackEvent': true,
        'PebbleRenderEvent': true,
        'PebbleTickEvent': true,
        'PropertyAnimation': true,
        'ResBankVersion': true,
        'ResHandle': true,
        'ResVersionHandle': true,
        'RotBmpContainer': true,
        'RotBmpLayer': true,
        'RotBmpPairContainer': true,
        'RotBmpPairLayer': true,
        'TextLayer': true,
        'TimeUnits': true,
        'VibePattern': true,
        'Window': true,
        'WindowButtonEventHandler': true,
        'WindowHandler': true,
        'WindowHandlers': true,
        'WindowInputHandlers': true,
        'ANIMATION_NORMALIZED_MAX': true,
        'ANIMATION_NORMALIZED_MIN': true,
        'APP_INFO_STANDARD_APP': true,
        'APP_INFO_VISIBILITY_HIDDEN': true,
        'APP_INFO_VISIBILITY_SHOWN_ON_COMMUNICATION': true,
        'APP_INFO_WATCH_FACE': true,
        'AnimationCurveEaseIn': true,
        'AnimationCurveEaseInOut': true,
        'AnimationCurveEaseOut': true,
        'AnimationCurveLinear': true,
        'BUTTON_ID_BACK': true,
        'BUTTON_ID_DOWN': true,
        'BUTTON_ID_SELECT': true,
        'BUTTON_ID_UP': true,
        'DAY_UNIT': true,
        'FONT_KEY_DROID_SERIF_28_BOLD': true,
        'FONT_KEY_FONT_FALLBACK': true,
        'FONT_KEY_GOTHAM_18_LIGHT_SUBSET': true,
        'FONT_KEY_GOTHAM_30_BLACK': true,
        'FONT_KEY_GOTHAM_34_LIGHT_SUBSET': true,
        'FONT_KEY_GOTHAM_34_MEDIUM_NUMBERS': true,
        'FONT_KEY_GOTHAM_42_BOLD': true,
        'FONT_KEY_GOTHAM_42_LIGHT': true,
        'FONT_KEY_GOTHAM_42_MEDIUM_NUMBERS': true,
        'FONT_KEY_BITHAM_18_LIGHT_SUBSET': true,
        'FONT_KEY_BITHAM_30_BLACK': true,
        'FONT_KEY_BITHAM_34_LIGHT_SUBSET': true,
        'FONT_KEY_BITHAM_34_MEDIUM_NUMBERS': true,
        'FONT_KEY_BITHAM_42_BOLD': true,
        'FONT_KEY_BITHAM_42_LIGHT': true,
        'FONT_KEY_BITHAM_42_MEDIUM_NUMBERS': true,
        'FONT_KEY_GOTHIC_14': true,
        'FONT_KEY_GOTHIC_14_BOLD': true,
        'FONT_KEY_GOTHIC_18': true,
        'FONT_KEY_GOTHIC_18_BOLD': true,
        'FONT_KEY_GOTHIC_24': true,
        'FONT_KEY_GOTHIC_24_BOLD': true,
        'FONT_KEY_GOTHIC_28': true,
        'FONT_KEY_GOTHIC_28_BOLD': true,
        'GAlignBottom': true,
        'GAlignBottomLeft': true,
        'GAlignBottomRight': true,
        'GAlignCenter': true,
        'GAlignLeft': true,
        'GAlignRight': true,
        'GAlignTop': true,
        'GAlignTopLeft': true,
        'GAlignTopRight': true,
        'GColorBlack': true,
        'GColorClear': true,
        'GColorWhite': true,
        'GCompOpAnd': true,
        'GCompOpAssign': true,
        'GCompOpAssignInverted': true,
        'GCompOpClear': true,
        'GCompOpOr': true,
        'GCornerBottomLeft': true,
        'GCornerBottomRight': true,
        'GCornerNone': true,
        'GCornerTopLeft': true,
        'GCornerTopRight': true,
        'GCornersAll': true,
        'GCornersBottom': true,
        'GCornersLeft': true,
        'GCornersRight': true,
        'GCornersTop': true,
        'GTextAlignmentCenter': true,
        'GTextAlignmentLeft': true,
        'GTextAlignmentRight': true,
        'GTextOverflowModeTrailingEllipsis': true,
        'GTextOverflowModeWordWrap': true,
        'HOUR_UNIT': true,
        'MINUTE_UNIT': true,
        'MONTH_UNIT': true,
        'NUM_BUTTONS': true,
        'NumAnimationCurve': true,
        'SECOND_UNIT': true,
        'TRIG_MAX_ANGLE': true,
        'TRIG_MAX_RATIO': true,
        'YEAR_UNIT': true
    }
};
//var browserHeight = document.documentElement.clientHeight;
//code_mirror.getWrapperElement().style.height = (browserHeight - 130) + 'px';
//code_mirror.refresh();
//code_mirror.refresh();
//code_mirror.on('cursorActivity', function() {
//    code_mirror.matchHighlight('CodeMirror-matchhighlight');
//})
