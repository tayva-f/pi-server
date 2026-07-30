var ServoTest = {
    servos: [],
    socket: null,

    init: function (socket) {
        ServoTest.socket = socket;
        $.get('/api/servos', function (data) {
            ServoTest.servos = data;
            ServoTest.render();
        });
    },

    render: function () {
        var container = $('#servo-test-sliders');
        container.empty();

        ServoTest.servos.forEach(function (servo) {
            var row = $('<div class="servo-row">');
            var label = $('<span class="servo-label">').text(servo.name);
            var slider = $('<input type="range">')
                .attr('min', servo.min)
                .attr('max', servo.max)
                .val(servo.current_angle != null ? servo.current_angle : servo.center)
                .addClass('servo-slider');
            var btnCenter = $('<button>').text('Center').addClass('btn-small').on('click', function () {
                slider.val(servo.center);
                slider.trigger('input');
            });
            var valText = $('<span class="servo-value">').text((servo.current_angle != null ? servo.current_angle : servo.center) + '\u00B0');

            var setAngle = function () {
                var v = parseInt(slider.val());
                valText.text(v + '\u00B0');
                if (ServoTest.socket) {
                    ServoTest.socket.emit('servo_set', { id: servo.id, angle: v });
                }
            };

            slider.on('input', setAngle);
            row.append(label, slider, valText, btnCenter);
            container.append(row);
        });
    }
};
