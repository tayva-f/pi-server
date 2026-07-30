var Editor = {
    animations: [],
    current: null,
    selectedKeyframe: null,
    servos: [],
    socket: null,
    viewDuration: 2000,
    _previewing: false,
    _dragKfId: null,
    _dragEnd: false,
    _dragStartX: 0,
    _dragStartTime: 0,
    _dragTimelineWidth: 0,

    init: function (socket) {
        Editor.socket = socket;
        Editor.socket.on('robot_state', Editor._onRobotState);
        Editor.loadServos();
        Editor.loadAnimations();
        $('#anim-add').on('click', Editor.addAnimation);
        $('#anim-delete').on('click', Editor.deleteAnimation);
        $('#anim-end').on('input', Editor.updateMeta);
        $('#anim-view').on('input', Editor.updateView);
        $('#anim-loop').on('change', Editor.updateMeta);
        $('#anim-name').on('input', Editor.updateName);
        $('#kf-add').on('click', Editor.addKeyframe);
        $('#kf-delete').on('click', Editor.deleteKeyframe);
        $('#anim-preview').on('click', Editor.preview);
        $('#anim-stop').on('click', Editor.stopPreview);

        $(document).on('mousemove', Editor._onDragMove);
        $(document).on('mouseup', Editor._onDragUp);
    },

    _onRobotState: function (data) {
        var playing = data.state === 'playing' && Editor.current && data.animation === Editor.current.name;
        $('#anim-preview').toggleClass('active-preview', playing);
        $('#anim-stop').toggleClass('active-stop', playing);
    },

    loadServos: function () {
        $.get('/api/servos', function (data) {
            Editor.servos = data;
            Editor.renderServoSliders();
        });
    },

    loadAnimations: function () {
        $.get('/api/animations', function (data) {
            Editor.animations = data;
            Editor.renderAnimList();
            if (data.length > 0 && !Editor.current) {
                Editor.selectAnimation(data[0].name);
            }
        });
    },

    renderAnimList: function () {
        var list = $('#anim-list');
        list.empty();
        Editor.animations.forEach(function (anim) {
            var item = $('<div>')
                .addClass('anim-list-item')
                .text(anim.name)
                .on('click', function () { Editor.selectAnimation(anim.name); });
            if (Editor.current && anim.name === Editor.current.name) {
                item.addClass('active');
            }
            list.append(item);
        });
    },

    selectAnimation: function (name) {
        $.get('/api/animations/' + encodeURIComponent(name), function (anim) {
            Editor.current = anim;
            Editor.selectedKeyframe = null;
            var end = anim.duration || 2000;
            if (end < 500) end = 500;
            Editor.current.duration = end;
            Editor.viewDuration = Math.max(end + 500, 2000);
            if (Editor.viewDuration < 1000) Editor.viewDuration = 1000;
            $('#anim-name').val(anim.name);
            $('#anim-end').val(end);
            $('#anim-view').val(Editor.viewDuration);
            $('#anim-loop').prop('checked', anim.loop);
            $('#editor-detail').show();
            Editor.renderAnimList();
            Editor.renderTimeline();
            Editor.renderServoSliders();
        });
    },

    addAnimation: function () {
        var name = prompt('Animation name:');
        if (!name) return;
        $.ajax({
            url: '/api/animations',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                name: name,
                loop: true,
                duration: 2000,
                keyframes: []
            }),
            success: function () {
                Editor.loadAnimations();
                Editor.selectAnimation(name);
            },
            error: function (xhr) {
                alert('Error: ' + (xhr.responseJSON && xhr.responseJSON.error || 'Unknown'));
            }
        });
    },

    deleteAnimation: function () {
        if (!Editor.current) return;
        if (!confirm('Delete "' + Editor.current.name + '"?')) return;
        $.ajax({
            url: '/api/animations/' + encodeURIComponent(Editor.current.name),
            method: 'DELETE',
            success: function () {
                Editor.current = null;
                Editor.selectedKeyframe = null;
                $('#editor-detail').hide();
                Editor.loadAnimations();
            }
        });
    },

    updateName: function () {
        if (!Editor.current) return;
        var newName = $('#anim-name').val().trim();
        if (!newName || newName === Editor.current.name) return;
        var oldName = Editor.current.name;
        Editor.current.name = newName;
        $.ajax({
            url: '/api/animations/' + encodeURIComponent(oldName),
            method: 'PUT',
            contentType: 'application/json',
            data: JSON.stringify(Editor.current),
            success: function () { Editor.renderAnimList(); },
            error: function () {
                Editor.current.name = oldName;
                $('#anim-name').val(oldName);
                Editor.renderAnimList();
            }
        });
    },

    updateView: function () {
        var v = parseInt($('#anim-view').val()) || 2000;
        if (v < 500) v = 500;
        Editor.viewDuration = v;
        Editor.renderTimeline();
    },

    updateMeta: function () {
        if (!Editor.current) return;
        var end = parseInt($('#anim-end').val()) || 2000;
        if (end < 500) end = 500;
        Editor.current.duration = end;
        Editor.current.loop = $('#anim-loop').is(':checked');
        Editor.saveCurrent();
        Editor.renderTimeline();
    },

    saveCurrent: function () {
        if (!Editor.current) return;
        $.ajax({
            url: '/api/animations/' + encodeURIComponent(Editor.current.name),
            method: 'PUT',
            contentType: 'application/json',
            data: JSON.stringify(Editor.current)
        });
    },

    renderTimeline: function () {
        var container = $('#timeline');
        container.empty();
        $('#timeline-cursor').remove();
        if (!Editor.current) return;

        var dur = Editor.current.duration || 2000;
        var view = Editor.viewDuration || 2000;
        var kfs = Editor.current.keyframes || [];
        kfs.sort(function (a, b) { return a.time - b.time; });

        // ── Time ticks every 100ms ──────────────────────
        for (var t = 0; t <= view; t += 100) {
            var tickLeft = (t / view) * 100;
            var major = t % 500 === 0;
            $('<div>').addClass('timeline-tick' + (major ? ' major' : ''))
                .css('left', tickLeft + '%')
                .appendTo(container);
            if (major && tickLeft <= 96) {
                $('<div>').addClass('timeline-tick-label')
                    .css('left', tickLeft + '%')
                    .text(t + 'ms')
                    .appendTo(container);
            }
        }

        // ── Interpolation segments ──────────────────────
        var colors = ['#F06449', '#4caf50', '#f4a261', '#6c5ce7', '#00b4d8', '#2ec4b6', '#e85d75', '#8e7cc3'];
        for (var i = 0; i < kfs.length; i++) {
            var next = kfs[(i + 1) % kfs.length];
            var segStart = (kfs[i].time / view) * 100;
            var segEnd;
            if (i + 1 < kfs.length) {
                segEnd = (next.time / view) * 100;
            } else {
                segEnd = (dur / view) * 100;
            }
            if (segEnd > segStart) {
                var color = colors[i % colors.length];
                $('<div>').addClass('timeline-segment')
                    .css({
                        left: segStart + '%',
                        width: (segEnd - segStart) + '%',
                        background: color,
                        opacity: 0.25
                    })
                    .attr('title', kfs[i].id + ' → ' + next.id + ' (' + (next.time - kfs[i].time) + 'ms)')
                    .appendTo(container);
            }
        }

        // ── End-point marker ────────────────────────────
        if (dur <= view) {
            var endLeft = (dur / view) * 100;
            $('<div>').addClass('end-marker-wrap')
                .css('left', endLeft + '%')
                .attr('title', 'End: ' + dur + 'ms — drag to set cycle length')
                .on('mousedown', function (e) {
                    e.stopPropagation();
                    e.preventDefault();
                    Editor._startEndDrag(e.pageX);
                })
                .appendTo(container);
            $('<div>').addClass('end-marker-handle')
                .css('left', endLeft + '%')
                .appendTo(container);
        }

        // ── Keyframe markers ────────────────────────────
        kfs.forEach(function (kf) {
            var left = (kf.time / view) * 100;
            var marker = $('<div>')
                .addClass('kf-marker')
                .css('left', left + '%')
                .attr('title', kf.id + ' @ ' + kf.time + 'ms')
                .on('mousedown', function (e) {
                    e.stopPropagation();
                    e.preventDefault();
                    Editor._startDrag(kf.id, e.pageX);
                })
                .on('click', function (e) {
                    e.stopPropagation();
                    Editor.selectKeyframe(kf.id);
                });
            if (Editor.selectedKeyframe && Editor.selectedKeyframe.id === kf.id) {
                marker.addClass('kf-selected');
            }
            container.append(marker);
        });

        container.off('click').on('click', function (e) {
            if (Editor._dragKfId || Editor._dragEnd) return;
            var offset = $(this).offset().left;
            var width = $(this).width();
            var x = e.pageX - offset;
            var time = Math.round((x / width) * view);
            Editor.selectedKeyframe = null;
            Editor.renderServoSliders();
            Editor.highlightTimelineCursor(time);
        });
    },

    _startDrag: function (kfId, pageX) {
        Editor._dragKfId = kfId;
        Editor._dragEnd = false;
        Editor._dragStartX = pageX;
        var kf = Editor.current.keyframes.find(function (k) { return k.id === kfId; });
        if (kf) Editor._dragStartTime = kf.time;
        Editor._dragTimelineWidth = $('#timeline').width();
        $('body').addClass('dragging');
    },

    _startEndDrag: function (pageX) {
        Editor._dragEnd = true;
        Editor._dragKfId = null;
        Editor._dragStartX = pageX;
        Editor._dragStartTime = Editor.current.duration;
        Editor._dragTimelineWidth = $('#timeline').width();
        $('body').addClass('dragging');
    },

    _onDragMove: function (e) {
        if ((!Editor._dragKfId && !Editor._dragEnd) || !Editor.current) return;
        var view = Editor.viewDuration || 2000;
        var dx = e.pageX - Editor._dragStartX;
        var dt = Math.round((dx / Editor._dragTimelineWidth) * view);
        var newTime = Math.max(0, Editor._dragStartTime + dt);

        if (Editor._dragEnd) {
            newTime = Math.round(newTime / 100) * 100;
            if (newTime < 500) newTime = 500;
            Editor.current.duration = newTime;
            $('#anim-end').val(newTime);
            Editor.renderTimeline();
            return;
        }

        newTime = Math.round(newTime / 50) * 50;

        var kf = Editor.current.keyframes.find(function (k) { return k.id === Editor._dragKfId; });
        if (!kf) return;
        var clash = Editor.current.keyframes.find(function (k) {
            return k.id !== Editor._dragKfId && k.time === newTime;
        });
        if (clash) return;

        kf.time = newTime;
        var left = (newTime / view) * 100;
        $('.kf-marker').each(function () {
            if ($(this).attr('title') && $(this).attr('title').indexOf(Editor._dragKfId) === 0) {
                $(this).css('left', left + '%');
                $(this).attr('title', Editor._dragKfId + ' @ ' + newTime + 'ms');
            }
        });
    },

    _onDragUp: function () {
        if (Editor._dragKfId || Editor._dragEnd) {
            if (Editor._dragKfId) Editor.selectKeyframe(Editor._dragKfId);
            Editor.saveCurrent();
            Editor.renderTimeline();
            Editor._dragKfId = null;
            Editor._dragEnd = false;
        }
        $('body').removeClass('dragging');
    },

    selectKeyframe: function (id) {
        if (!Editor.current) return;
        var kf = Editor.current.keyframes.find(function (k) { return k.id === id; });
        if (kf) {
            Editor.selectedKeyframe = kf;
            Editor.renderTimeline();
            Editor.renderServoSliders();
            Editor._previewKeyframe(kf);
        }
    },

    _previewKeyframe: function (kf) {
        if (!Editor.socket) return;
        Object.keys(kf.angles).forEach(function (sId) {
            Editor.socket.emit('servo_set', { id: sId, angle: kf.angles[sId] });
        });
    },

    addKeyframe: function () {
        if (!Editor.current) return;
        var kfs = Editor.current.keyframes;
        var id = 'kf_' + Date.now();
        var end = Editor.current.duration || 2000;

        var timeOffsets = kfs.map(function (k) { return k.time; });
        var nextTime = 0;
        while (nextTime < end - 50 && timeOffsets.indexOf(nextTime) !== -1) {
            nextTime += 100;
        }
        if (nextTime >= end - 50) {
            nextTime = end - 50;
            while (nextTime > 0 && timeOffsets.indexOf(nextTime) !== -1) {
                nextTime -= 50;
            }
            if (nextTime < 0 || timeOffsets.indexOf(nextTime) !== -1) {
                nextTime = 0;
            }
        }

        var angles = {};
        Editor.servos.forEach(function (s) {
            angles[s.id] = s.center;
        });

        var kf = { id: id, time: nextTime, angles: angles };
        kfs.push(kf);
        Editor.selectedKeyframe = kf;
        Editor.saveCurrent();
        Editor.renderTimeline();
        Editor.renderServoSliders();
    },

    deleteKeyframe: function () {
        if (!Editor.current || !Editor.selectedKeyframe) return;
        Editor.current.keyframes = Editor.current.keyframes.filter(function (k) {
            return k.id !== Editor.selectedKeyframe.id;
        });
        Editor.selectedKeyframe = null;
        Editor.saveCurrent();
        Editor.renderTimeline();
        Editor.renderServoSliders();
    },

    highlightTimelineCursor: function (time) {
        $('#timeline-cursor').remove();
        if (!Editor.current) return;
        var view = Editor.viewDuration || 2000;
        var left = (time / view) * 100;
        $('<div id="timeline-cursor">').css('left', left + '%').appendTo('#timeline');
    },

    renderServoSliders: function () {
        var container = $('#servo-sliders');
        container.empty();
        var angles = Editor.selectedKeyframe ? Editor.selectedKeyframe.angles : {};

        Editor.servos.forEach(function (servo) {
            var val = angles[servo.id] !== undefined ? angles[servo.id] : servo.center;
            var row = $('<div class="servo-row">');
            var label = $('<span class="servo-label">').text(servo.name);
            var slider = $('<input type="range">')
                .attr('min', servo.min)
                .attr('max', servo.max)
                .val(val)
                .addClass('servo-slider');
            var valText = $('<span class="servo-value">').text(val + '\u00B0');

            (function (sId) {
                slider.on('input', function () {
                    var v = parseInt($(this).val());
                    valText.text(v + '\u00B0');
                    if (Editor.selectedKeyframe) {
                        Editor.selectedKeyframe.angles[sId] = v;
                        Editor.saveCurrent();
                    }
                    if (Editor.socket) {
                        Editor.socket.emit('servo_set', { id: sId, angle: v });
                    }
                });
            })(servo.id);

            row.append(label, slider, valText);
            container.append(row);
        });

        if (!Editor.selectedKeyframe) {
            container.prepend($('<div class="servo-hint">').text('Select a keyframe on the timeline to edit servo positions for that frame.'));
        } else {
            container.prepend($('<div class="servo-hint">').text('Editing keyframe: ' + Editor.selectedKeyframe.id + ' at ' + Editor.selectedKeyframe.time + 'ms'));
        }
    },

    preview: function () {
        if (!Editor.current) return;
        $.post('/api/animations/' + encodeURIComponent(Editor.current.name) + '/preview');
    },

    stopPreview: function () {
        $.post('/api/animations/stop');
    }
};
