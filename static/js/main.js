function setMicStatus(state, message) {
    var dot = document.getElementById('status-dot');
    var text = document.getElementById('status-text');
    var colors = { idle: 'gray', connecting: '#F06449', live: '#4caf50', error: '#c0392b' };
    dot.style.background = colors[state] || 'gray';
    text.textContent = message;
}

function showMeter(visible) {
    document.getElementById('audio-meter').style.display = visible ? 'block' : 'none';
}

var currentStream = null;
var audioCtx = null;
var analyser = null;
var source = null;
var processor = null;
var silentGain = null;
var dataArray = null;
var isConnecting = false;

var socket = io();

socket.on('connect', function () {
    if (currentStream) {
        setMicStatus('live', 'Microphone live');
    }
});

socket.on('disconnect', function () {
    if (currentStream) {
        setMicStatus('connecting', 'Reconnecting...');
    }
});

socket.on('robot_state', function (data) {
    var stateEl = document.getElementById('robot-state');
    if (stateEl) {
        if (data.state === 'playing') {
            stateEl.textContent = 'Playing: ' + (data.animation || 'unknown');
            stateEl.style.color = '#4caf50';
        } else if (data.animation) {
            stateEl.textContent = 'Idle: ' + data.animation;
            stateEl.style.color = '#555';
        } else if (data.paused) {
            stateEl.textContent = 'Paused';
            stateEl.style.color = '#F06449';
        } else {
            stateEl.textContent = 'Idle';
            stateEl.style.color = '#555';
        }
    }
    var pauseCheck = document.getElementById('anim-paused-check');
    if (pauseCheck) {
        pauseCheck.checked = data.paused || false;
    }
});

// ── Tab switching ─────────────────────────────────────────

$('.tab-btn').on('click', function () {
    var tab = $(this).data('tab');
    $('.tab-btn').removeClass('active');
    $(this).addClass('active');
    $('.tab-content').removeClass('active');
    $('#' + tab + '-tab').addClass('active');

    if (tab === 'editor') {
        Editor.loadServos();
        Editor.loadAnimations();
    } else if (tab === 'keymapper') {
        KeyMapper.load();
    } else if (tab === 'servos') {
        Servos.load();
    } else if (tab === 'home') {
        loadIdleSettings();
    }
});

// ── Keyboard input ───────────────────────────────────────

var heldKeys = {};
$(document).on('keydown', function (event) {
    if (KeyMapper.pendingKey !== null) return;
    if (heldKeys[event.key]) return;
    heldKeys[event.key] = true;
    socket.emit('keydown', { key: event.key });
});

$(document).on('keyup', function (event) {
    if (KeyMapper.pendingKey !== null) return;
    heldKeys[event.key] = false;
    socket.emit('keyup', { key: event.key });
});

// ── Idle animation & pause ───────────────────────────────

function loadIdleSettings() {
    $.get('/api/idle-animation', function (data) {
        $('.idle-anim-opt[value!=""]').remove();
        $.get('/api/animations', function (anims) {
            anims.forEach(function (a) {
                var opt = $('<option>').addClass('idle-anim-opt').val(a.name).text(a.name);
                if (data.name === a.name) opt.prop('selected', true);
                $('#idle-anim-select').append(opt);
            });
        });
    });
    $.get('/api/animation-paused', function (data) {
        $('#anim-paused-check').prop('checked', data.paused);
    });
}

$('#idle-anim-select').on('change', function () {
    $.ajax({
        url: '/api/idle-animation',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ name: $(this).val() || null })
    });
});

$('#anim-paused-check').on('change', function () {
    $.ajax({
        url: '/api/animation-paused',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ paused: $(this).is(':checked') })
    });
});

$('#mic-toggle').on('click', function () {
    if (isConnecting) return;
    if (currentStream) {
        disconnectMic();
        connectMic();
    } else {
        connectMic();
    }
});

$('#device-confirm').on('click', function () {
    var selectedId = $('#device-select').val();
    $('#device-selector').hide();
    finishConnectWithDevice(selectedId);
});

$('#device-cancel').on('click', function () {
    $('#device-selector').hide();
    setMicStatus('idle', 'No microphone connected');
});

function disconnectMic() {
    if (audioCtx) {
        audioCtx.close().catch(function () {});
    }
    if (currentStream) {
        currentStream.getTracks().forEach(function (t) { t.stop(); });
    }
    currentStream = null;
    audioCtx = null;
    analyser = null;
    source = null;
    processor = null;
    silentGain = null;
    dataArray = null;
    showMeter(false);
    setMicStatus('idle', 'No microphone connected');
    $('#mic-toggle').text('Connect Microphone');
}

async function connectMic() {
    isConnecting = true;
    setMicStatus('connecting', 'Requesting microphone...');

    var stream;
    try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
        handleMicError(err);
        isConnecting = false;
        return;
    }

    var devices = [];
    try {
        devices = await navigator.mediaDevices.enumerateDevices();
    } catch (_) {}
    var audioInputs = devices.filter(function (d) { return d.kind === 'audioinput'; });

    if (audioInputs.length <= 1) {
        buildAudioGraph(stream);
    } else {
        stream.getTracks().forEach(function (t) { t.stop(); });
        showDeviceSelector(audioInputs);
    }
    isConnecting = false;
}

function showDeviceSelector(devices) {
    var select = $('#device-select');
    select.empty();
    devices.forEach(function (d, i) {
        var label = d.label || ('Microphone ' + (i + 1));
        select.append($('<option>').val(d.deviceId).text(label));
    });
    $('#device-selector').css('display', 'flex');
    setMicStatus('connecting', 'Select a microphone below');
}

async function finishConnectWithDevice(deviceId) {
    setMicStatus('connecting', 'Connecting to selected microphone...');

    var stream;
    try {
        stream = await navigator.mediaDevices.getUserMedia({
            audio: { deviceId: { exact: deviceId } }
        });
    } catch (err) {
        handleMicError(err);
        return;
    }

    buildAudioGraph(stream);
}

function handleMicError(err) {
    if (err.name === 'NotAllowedError') {
        setMicStatus('error', 'Microphone access denied — allow mic access and refresh');
    } else if (err.name === 'NotFoundError') {
        setMicStatus('error', 'No microphone found — connect a mic and try again');
    } else if (err.name === 'NotReadableError') {
        setMicStatus('error', 'Microphone is busy — close other apps using it');
    } else {
        setMicStatus('error', 'Mic error: ' + err.message);
    }
}

function buildAudioGraph(stream) {
    currentStream = stream;

    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') {
        audioCtx.resume().catch(function () {});
    }

    source = audioCtx.createMediaStreamSource(stream);
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);

    dataArray = new Uint8Array(analyser.frequencyBinCount);
    showMeter(true);

    function updateMeter() {
        if (!analyser) return;
        analyser.getByteTimeDomainData(dataArray);
        var sum = 0;
        for (var i = 0; i < dataArray.length; i++) {
            var v = (dataArray[i] - 128) / 128;
            sum += v * v;
        }
        var rms = Math.sqrt(sum / dataArray.length);
        document.getElementById('meter-bar').style.width = Math.min(rms * 100, 100) + '%';
        requestAnimationFrame(updateMeter);
    }
    requestAnimationFrame(updateMeter);

    var bufferSize = 4096;
    processor = audioCtx.createScriptProcessor(bufferSize, 1, 1);
    silentGain = audioCtx.createGain();
    silentGain.gain.value = 0;
    source.connect(processor);
    processor.connect(silentGain);
    silentGain.connect(audioCtx.destination);

    processor.onaudioprocess = function (e) {
        if (socket && socket.connected) {
            var float32 = e.inputBuffer.getChannelData(0);
            var int16 = new Int16Array(float32.length);
            for (var i = 0; i < float32.length; i++) {
                var s = Math.max(-1, Math.min(1, float32[i]));
                int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
            }
            socket.emit("audio", int16.buffer);
        }
    };

    setMicStatus('live', 'Microphone live');
    $('#mic-toggle').text('Change Microphone');
}

// ── Init modules ──────────────────────────────────────────

$(function () {
    Editor.init(socket);
    KeyMapper.init();
    Servos.init(socket);
    loadIdleSettings();
});
