function fetchReasonCodes() {
    // Hacer una llamada AJAX a Odoo
    $.ajax({
        url: '/l10n_es_edi_facturae/reason_codes',
        type: 'GET',
        success: function(response) {
            var reasonCodeSelect = document.getElementById("l10n_es_edi_facturae_reason_code");
            reasonCodeSelect.innerHTML = '';

            // Rellenar el campo con los códigos obtenidos
            response.options.forEach(function(option) {
                var opt = document.createElement('option');
                opt.value = option.id;
                opt.text = option.name;
                reasonCodeSelect.appendChild(opt);
            });
        },
        error: function(error) {
            console.log("Error fetching reason codes: ", error);
        }
    });
}

// Llamar a la función al cargar la página o en el momento que necesites
fetchReasonCodes();
