// fit.js — writes the panel height into <body data-h> so render.sh can size the screenshot exactly
document.fonts.ready.then(() => { document.body.dataset.h = Math.ceil(document.getElementById('cv').getBoundingClientRect().height) + 2; });
