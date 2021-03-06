CloudPebble.Editor = (function() {
    var THAT_ONE_JS_FILE = 'js/pebble-js-app.js'; // You'll probably want to grep this when adding multiple JS file support.:
    var project_source_files = {};
    var open_codemirrors = {};
    var unsaved_files = 0;
    var is_fullscreen = false;

    var add_source_file = function(file) {
        CloudPebble.Sidebar.AddSourceFile(file, function() {
            edit_source_file(file);
        });

        project_source_files[file.name] = file;
        // If we're adding that one JS file, remove the link to add it.
        // (this arguably intrudes upon the sidebar's domain, but...)
        if(file.name == THAT_ONE_JS_FILE) {
            $('#new-js-file').hide();
        }
    };

    var edit_source_file = function(file) {
        // See if we already had it open.
        CloudPebble.Sidebar.SuspendActive();
        if(CloudPebble.Sidebar.Restore('source-'+file.id)) {
            return;
        }
        CloudPebble.ProgressBar.Show();

        // Open it.
        $.getJSON('/ide/project/' + PROJECT_ID + '/source/' + file.id + '/load', function(data) {
            CloudPebble.ProgressBar.Hide();
            if(!data.success) {
                var error = $('<div class="alert alert-error"></div>');
                error.text("Something went wrong: " + data.error);
                CloudPebble.Sidebar.SetActivePane(error, '');
            } else {
                var is_js = file.name.substr(-3) == '.js';
                var source = data.source;
                var pane = $('<div>');
                var is_autocompleting = false;
                var settings = {
                    indentUnit: 4,
                    lineNumbers: true,
                    autofocus: true,
                    electricChars: true,
                    matchBrackets: true,
                    autoCloseBrackets: true,
                    //highlightSelectionMatches: true,
                    smartIndent: true,
                    indentWithTabs: true,
                    mode: (is_js ? 'javascript' : CloudPebble.Editor.PebbleMode),
                    styleActiveLine: true,
                    value: source,
                    theme: USER_SETTINGS.theme
                };
                if(USER_SETTINGS.keybinds !== '') {
                    settings.keyMap = USER_SETTINGS.keybinds;
                }
                if(!is_js && USER_SETTINGS.autocomplete === 2) {
                    settings.extraKeys = {'Ctrl-Space': 'autocomplete'};
                }
                if(!is_js && USER_SETTINGS.autocomplete !== 0) {
                    if(!settings.extraKeys) settings.extraKeys = {};
                    settings.extraKeys['Tab'] = function() {
                        var marks = code_mirror.getAllMarks();
                        var cursor = code_mirror.getCursor();
                        var closest = null;
                        var closest_mark = null;
                        var distance = 99999999999; // eh
                        for (var i = marks.length - 1; i >= 0; i--) {
                            var mark = marks[i];
                            var pos = mark.find();
                            if(pos === undefined) continue;
                            if(cursor.line >= pos.from.line - 5) {
                                if(cursor.line < pos.from.line || cursor.ch <= pos.from.ch) {
                                    var new_distance = 100000 * (pos.from.line - cursor.line) + (pos.from.ch - cursor.ch);
                                    if(new_distance < distance) {
                                        closest = pos;
                                        closest_mark = mark;
                                        distance = new_distance;
                                    }
                                }
                            }
                        }
                        if(closest !== null) {
                            closest_mark.clear();
                            CloudPebble.Editor.Autocomplete.SelectPlaceholder(code_mirror, closest);
                        } else {
                            return CodeMirror.Pass;
                        }
                    };
                }
                if(is_js) {
                    settings.gutters = ['CodeMirror-linenumbers', 'gutter-hint-warnings'];
                }
                var code_mirror = CodeMirror(pane[0], settings);
                code_mirror.parent_pane = pane;
                open_codemirrors[file.id] = code_mirror;
                code_mirror.cloudpebble_save = function() {
                    save();
                };
                code_mirror.on('close', function() {
                    is_autocompleting = false;
                });
                code_mirror.on('shown', function() {
                    is_autocompleting = true;
                });
                if(!is_js && USER_SETTINGS.autocomplete === 1) {
                    code_mirror.on('change', function() {
                        if(!is_autocompleting)
                            CodeMirror.commands.autocomplete(code_mirror);
                    });
                }
                if(is_js) {
                    var warning_lines = [];
                    var throttled_hint = _.throttle(function() {
                        // Clear things out, even if jslint is off
                        // (the user might have just turned it off).
                        code_mirror.clearGutter('gutter-hint-warnings');
                        _.each(warning_lines, function(line) {
                            code_mirror.removeLineClass(line, 'background', 'line-hint-warning');
                        });
                        warning_lines = [];

                        // And now bail.
                        if(!CloudPebble.ProjectInfo.app_jshint) return;

                        var success = JSHINT(code_mirror.getValue(), {
                            freeze: true,
                            evil: false,
                            immed: true,
                            latedef: "nofunc",
                            undef: true,
                            unused: "vars"
                        }, {
                            Pebble: true,
                            console: true,
                            XMLHttpRequest: true,
                            navigator: true, // For navigator.geolocation
                            localStorage: true,
                            setTimeout: true
                        });
                        if(!success) {
                            _.each(JSHINT.errors, function(error) {
                                // If there are multiple errors on one line, we'll have already placed a marker here.
                                // Instead of replacing it with a new one, just update it.
                                var markers = code_mirror.lineInfo(error.line - 1).gutterMarkers;
                                if(markers && markers['gutter-hint-warnings']) {
                                    var marker = $(markers['gutter-hint-warnings']);
                                    marker.attr('title', marker.attr('title') + "\n" + error.reason);
                                } else {
                                    var warning = $('<div class="line-hint-warning"><i class="icon-warning-sign icon-white"></span></div>');
                                    warning.attr('title', error.reason);
                                    code_mirror.setGutterMarker(error.line - 1, 'gutter-hint-warnings', warning[0]);
                                    warning_lines.push(code_mirror.addLineClass(error.line - 1, 'background', 'line-hint-warning'));
                                }
                            });
                        }
                    }, 1000);
                    code_mirror.on('change', throttled_hint);
                    // Make sure we're ready when we start.
                    throttled_hint();
                }

                var fix_height = function() {
                    if(!is_fullscreen) {
                        var browserHeight = document.documentElement.clientHeight;
                        code_mirror.getWrapperElement().style.height = browserHeight - 130 + 'px';
                        code_mirror.refresh();
                    }
                };
                fix_height();
                $(window).resize(fix_height);

                CloudPebble.Sidebar.SetActivePane(pane, 'source-' + file.id, function() {
                    code_mirror.refresh();
                    code_mirror.focus();
                }, function() {
                    if(!was_clean) {
                        --unsaved_files;
                    }
                    delete open_codemirrors[file.id];
                });

                var was_clean = true;
                code_mirror.on('change', function() {
                    if(was_clean) {
                        CloudPebble.Sidebar.SetIcon('source-' + file.id, 'edit');
                        was_clean = false;
                        ++unsaved_files;
                    }
                });

                var mark_clean = function() {
                    was_clean = true;
                    --unsaved_files;
                    CloudPebble.Sidebar.ClearIcon('source-' + file.id);
                };

                var save = function() {
                    save_btn.attr('disabled','disabled');
                    delete_btn.attr('disabled','disabled');
                    $.post("/ide/project/" + PROJECT_ID + "/source/" + file.id + "/save", {'content': code_mirror.getValue()}, function(data) {
                        save_btn.removeAttr('disabled');
                        delete_btn.removeAttr('disabled');
                        if(data.success) {
                            mark_clean();
                            ga('send', 'event' ,'file', 'save');
                        } else {
                            alert(data.error);
                        }
                    });
                };

                // Add some buttons
                var button_holder = $('<p style="padding-top: 5px; text-align: right;" id="buttons_wrapper">');
                var save_btn = $('<button class="btn btn-primary">Save</button>');
                var discard_btn = $('<button class="btn" style="margin-right: 20px;">Reload file</button>');
                var delete_btn = $('<button class="btn btn-danger" style="margin-right: 20px;">Delete</button>');
                var error_area = $('<div>');

                save_btn.click(save);
                delete_btn.click(function() {
                    CloudPebble.Prompts.Confirm("Do you want to delete " + file.name + "?", "This cannot be undone.", function() {
                        save_btn.attr('disabled','disabled');
                        delete_btn.attr('disabled','disabled');
                        $.post("/ide/project/" + PROJECT_ID + "/source/" + file.id + "/delete", function(data) {
                            save_btn.removeAttr('disabled');
                            delete_btn.removeAttr('disabled');
                            if(data.success) {
                                CloudPebble.Sidebar.DestroyActive();
                                delete project_source_files[file.name];
                                CloudPebble.Sidebar.Remove('source-' + file.id);
                                // Restore the add JS button if we just removed it.
                                if(file.name == THAT_ONE_JS_FILE) {
                                    $('#new-js-file').show();
                                }
                            } else {
                                alert(data.error);
                            }
                        });
                        ga('send', 'event', 'file', 'delete');
                    });
                });

                discard_btn.click(function() {
                    CloudPebble.Prompts.Confirm(
                        "Do you want to reload " + file.name + "?",
                        "This will discard your current changes and revert to the saved version.",
                        function() {
                            CloudPebble.Sidebar.DestroyActive();
                            mark_clean();
                            edit_source_file(file);
                        }
                    );
                });

                button_holder.append(error_area);
                button_holder.append(delete_btn);
                button_holder.append(discard_btn);
                button_holder.append(save_btn);
                pane.append(button_holder);
                code_mirror.refresh();

                // Add fullscreen icon and click event
                var fullscreen_icon = $('<a href="#" class="fullscreen-icon open"></a><span class="fullscreen-icon-tooltip">Toggle Fullscreen</span>');
                $(code_mirror.getWrapperElement()).append(fullscreen_icon);
                fullscreen_icon.click(function(e) {
                    fullscreen(code_mirror, !is_fullscreen);
                });
                fullscreen_icon.hover(function() {
                    $('.fullscreen-icon-tooltip').fadeIn(300);
                },function() {
                    $('.fullscreen-icon-tooltip').fadeOut(300);
                });

                $(document).keyup(function(e) {
                  if (e.keyCode == 27) { fullscreen(code_mirror, false); }   // Esc exits fullscreen mode
                });

                // Tell Google
                ga('send', 'event', 'file', 'open');
            }
        });
    };

    function init() {
        CodeMirror.commands.autocomplete = function(cm) {
            CodeMirror.showHint(cm, CloudPebble.Editor.Autocomplete.Complete, {completeSingle: false});
        };
        CodeMirror.commands.save = function(cm) {
            cm.cloudpebble_save();
        };
        CodeMirror.commands.saveAll = function(cm) {
            $.each(open_codemirrors, function(index, value) {
                value.cloudpebble_save();
            });
        };
     }

    function fullscreen(code_mirror, toggle) {
        if(toggle) {
            $(code_mirror.getWrapperElement())
                .addClass('FullScreen')
                .css({'height': '100%'})
                .appendTo($('body'));
        } else {
            var browserHeight = document.documentElement.clientHeight;
            var newHeight = (browserHeight - 130) + 'px';
            $(code_mirror.getWrapperElement())
                .removeClass('FullScreen')
                .css({'height' : newHeight})
                .prependTo(code_mirror.parent_pane);
        }
        code_mirror.refresh();
        is_fullscreen = toggle;
     }

    return {
        Create: function() {
            CloudPebble.Prompts.Prompt("New Source File", "Enter a name for the new file", "somefile.c", '', function(value, resp) {
               if(value === '') {
                    resp.error("You must specify a filename.");
                } else if(!(/\.h$/.test(value) || /\.c$/.test(value))) {
                    resp.error("Source files must end in .c or .h");
                } else if(project_source_files[value]) {
                    resp.error("A file called '" + value + "' already exists.");
                } else {
                    resp.disable();
                    $.post("/ide/project/" + PROJECT_ID + "/create_source_file", {'name': value}, function(data) {
                        if(!data.success) {
                            resp.error(data.error);
                        } else {
                            resp.dismiss();
                            add_source_file(data.file);
                            edit_source_file(data.file);
                        }
                    });
                    ga('send', 'event', 'file', 'create');
                }
            });
        },
        DoJSFile: function() {
            $.post("/ide/project/" + PROJECT_ID + "/create_source_file", {'name': THAT_ONE_JS_FILE}, function(data) {
                if(!data.success) {
                    alert(data.error);
                } else {
                    add_source_file(data.file);
                    edit_source_file(data.file);
                }
            });
        },
        Add: function(file) {
            add_source_file(file);
        },
        Init: function() {
            init();
        },
        GetUnsavedFiles: function() {
            return unsaved_files;
        }
    };
})();
