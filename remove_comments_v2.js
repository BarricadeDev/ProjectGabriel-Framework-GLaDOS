const fs = require('fs');
const content = fs.readFileSync('e:\\Github\\ProjectGabriel-Framework\\v2.py', 'utf8');
const cleaned = content.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^(\s*)#.*$)/gm, '$2').replace(/\s#.*$/gm, '');
fs.writeFileSync('e:\\Github\\ProjectGabriel-Framework\\v2.py', cleaned);