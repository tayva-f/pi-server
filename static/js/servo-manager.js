var Servos = {
    servos: [],
    socket: null,

    init: function (socket) {
        Servos.socket = socket;
        $('#servo-add-btn').on('click', Servos.addServo);
        $('#servo-test-pin-btn').on('click', Servos.testPin);
        $('#servo-refresh').on('click', function () { Servos.load(); });
        Servos.load();
    },

    load: function () {
        $.get('/api/servos', function (data) {
            Servos.servos = data;
            Servos.render();
        });
    },

    render: function () {
        var container = $('#servo-list');
        container.empty();

        Servos.servos.forEach(function (servo) {
            var card = $('<div class="servo-card">');
            var header = $('<div class="servo-card-header">');
            var namePin = $('<span>').text(servo.name + ' (Pin ' + servo.pin + ', ' + servo.min + '\u00B0-' + servo.max + '\u00B0, center ' + servo.center + '\u00B0)');
            var btns = $('<span>');
            var testBtn = $('<button class="btn-small">').text('Test Pin').on('click', function () {
                $.post('/api/servos/' + servo.id + '/test').fail(function () {
                    alert('Failed to test servo: ' + servo.name);
                });
            });
            var delBtn = $('<button class="btn-small" style="border-color:#F06449;color:#F06449;">').text('Delete').on('click', function () {
                if (!confirm('Delete servo "' + servo.name + '"?')) return;
                $.ajax({ url: '/api/servos/' + servo.id, method: 'DELETE', success: function () { Servos.load(); } });
            });
            btns.append(testBtn, ' ', delBtn);
            header.append(namePin, btns);

            var sliderRow = $('<div class="servo-row">');
            var slider = $('<input type="range">')
                .attr('min', servo.min)
                .attr('max', servo.max)
                .val(servo.current_angle != null ? servo.current_angle : servo.center)
                .addClass('servo-slider');
            var valText = $('<span class="servo-value">').text((servo.current_angle != null ? servo.current_angle : servo.center) + '\u00B0');
            var centerBtn = $('<button class="btn-small">').text('Center').on('click', function () {
                slider.val(servo.center); slider.trigger('input');
            });

            slider.on('input', function () {
                var v = parseInt($(this).val());
                valText.text(v + '\u00B0');
                if (Servos.socket) {
                    Servos.socket.emit('servo_set', { id: servo.id, angle: v });
                }
            });

            sliderRow.append(slider, valText, centerBtn);
            card.append(header, sliderRow);
            container.append(card);
        });
    },

    addServo: function () {
        var name = $('#servo-new-name').val().trim();
        var pinVal = parseInt($('#servo-new-pin').val());
        var minVal = parseInt($('#servo-new-min').val());
        var maxVal = parseInt($('#servo-new-max').val());
        var centerVal = parseInt($('#servo-new-center').val());

        var pin = isNaN(pinVal) ? null : pinVal;
        var min = isNaN(minVal) ? 0 : minVal;
        var max = isNaN(maxVal) ? 180 : maxVal;
        var center = isNaN(centerVal) ? Math.round((min + max) / 2) : centerVal;

        if (!name || pin === null) {
            alert('Enter a name and pin number.');
            return;
        }

        $.ajax({
            url: '/api/servos',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ name: name, pin: pin, min: min, max: max, center: center }),
            success: function () {
                $('#servo-new-name').val('');
                $('#servo-new-pin').val('');
                Servos.load();
            },
            error: function (xhr) {
                alert('Error: ' + (xhr.responseJSON && xhr.responseJSON.error || 'Unknown'));
            }
        });
    },

    testPin: function () {
        var pinVal = parseInt($('#servo-new-pin').val());
        if (isNaN(pinVal)) {
            alert('Enter a GPIO pin number first.');
            return;
        }
        $.ajax({
            url: '/api/servo-pin/test',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ pin: pinVal })
        }).fail(function () {
            alert('Failed to test pin ' + pinVal);
        });
    }
};
