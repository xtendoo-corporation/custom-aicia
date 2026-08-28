document.getElementById("move_type").addEventListener("change", function() {
    var moveType = document.getElementById("move_type").value;
    var reasonField = document.getElementById("reason_field");

    if (moveType === "out_invoice") {
        reasonField.style.display = "none"; // Ocultar el campo de reason
    } else {
        reasonField.style.display = "block"; // Mostrar el campo de reason
    }
});

// Ejecutar al cargar la página para ocultar el campo basado en la selección inicial
window.addEventListener('load', function() {
    var moveType = document.getElementById("move_type").value;
    var reasonField = document.getElementById("reason_field");

    if (moveType === "out_invoice") {
        reasonField.style.display = "none"; // Ocultar el campo si el tipo es 'out_invoice'
    } else {
        reasonField.style.display = "block"; // Mostrar el campo si el tipo no es 'out_invoice'
    }
});
