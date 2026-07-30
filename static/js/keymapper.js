var KeyMapper = {
    bindings: {},
    animNames: [],
    pendingKey: null,

    init: function () {
        KeyMapper.load();

        $('#km-refresh').on('click', function () { KeyMapper.load(); });
        $('#km-add').on('click', function () { KeyMapper.startCapture(null); });

        $(document).on('keydown', function (e) {
            if (KeyMapper.pendingKey !== null) {
                e.preventDefault();
                KeyMapper.captureKey(e.key);
            }
        });
    },

    load: function () {
        $.get('/api/bindings', function (data) {
            KeyMapper.bindings = data || {};
            $.get('/api/animations', function (anims) {
                KeyMapper.animNames = anims.map(function (a) { return a.name; });
                KeyMapper.render();
            });
        });
    },

    render: function () {
        var tbody = $('#km-table-body');
        tbody.empty();

        Object.keys(KeyMapper.bindings).sort().forEach(function (key) {
            var anim = KeyMapper.bindings[key];
            var row = $('<tr>');
            var keyCell = $('<td>').text(key);
            var animCell = $('<td>').text(anim);
            var actionCell = $('<td>');
            var changeBtn = $('<button>').text('Change').on('click', function () {
                KeyMapper.startCapture(key);
            });
            var removeBtn = $('<button>').text('Remove').on('click', function () {
                delete KeyMapper.bindings[key];
                KeyMapper.save();
                KeyMapper.render();
            });
            actionCell.append(changeBtn, ' ', removeBtn);
            row.append(keyCell, animCell, actionCell);
            tbody.append(row);
        });
    },

    startCapture: function (existingKey) {
        KeyMapper.pendingKey = existingKey === null ? '' : existingKey;
        $('#km-capture-status').text('Press a key to bind...').css('color', '#F06449');

        var animSelector = $('#km-anim-select');
        animSelector.empty();
        animSelector.append($('<option>').val('').text('-- Select Animation --'));
        KeyMapper.animNames.forEach(function (name) {
            var selected = existingKey && KeyMapper.bindings[existingKey] === name;
            animSelector.append($('<option>').val(name).text(name).prop('selected', selected));
        });
        $('#km-capture').show();
    },

    captureKey: function (key) {
        if (KeyMapper.pendingKey === null) return;
        var oldKey = KeyMapper.pendingKey;

        if (oldKey && oldKey !== '' && KeyMapper.bindings[oldKey]) {
            delete KeyMapper.bindings[oldKey];
        }
        KeyMapper.pendingKey = key;
        $('#km-capture-status').text('Key captured: "' + key + '" — select animation below').css('color', '#4caf50');
    },

    confirm: function () {
        var animName = $('#km-anim-select').val();
        if (!KeyMapper.pendingKey || !animName) {
            alert('Capture a key and select an animation first.');
            return;
        }
        KeyMapper.bindings[KeyMapper.pendingKey] = animName;
        KeyMapper.pendingKey = null;
        KeyMapper.save();
        $('#km-capture').hide();
        KeyMapper.render();
    },

    cancelCapture: function () {
        KeyMapper.pendingKey = null;
        $('#km-capture').hide();
        $('#km-capture-status').text('Press a key to bind...').css('color', '#F06449');
    },

    save: function () {
        $.ajax({
            url: '/api/bindings',
            method: 'PUT',
            contentType: 'application/json',
            data: JSON.stringify(KeyMapper.bindings)
        });
    }
};
