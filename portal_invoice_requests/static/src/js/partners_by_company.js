function fetchPartnersByCompany() {
    var companyId = document.getElementById("company_id").value;

    // Hacer una llamada AJAX a Odoo
    $.ajax({
        url: '/partners_by_company',
        type: 'GET',
        data: { company_id: companyId }, // Pasar el company_id como parámetro
        success: function(response) {
            var partnerSelect = document.getElementById("partner_id");
            partnerSelect.innerHTML = '';

            // Rellenar el campo con los partners filtrados
            response.partners.forEach(function(partner) {
                var option = document.createElement('option');
                option.value = partner.id;
                option.text = partner.name;
                partnerSelect.appendChild(option);
            });
        },
        error: function(error) {
            console.log("Error fetching partners: ", error);
        }
    });
}
