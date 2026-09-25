#!/usr/bin/env node
// Cross-implementation JCS vectors for gen2/tests/test_canonical.py.
//
// Independent oracle for Astra ruling R1: the canonicalizer below is RFC 8785
// Appendix A ("ECMAScript Sample Canonicalizer") copied verbatim, running on
// V8's own JSON.parse/JSON.stringify — i.e. the ECMAScript behaviour JCS is
// defined by — not on the pinned Python rfc8785 package under test.
//
// Usage: node tools/gen2_jcs_cross_vectors.js < inputs.json
//   inputs.json: a JSON array of JSON *texts* (strings).
// Output: one JSON object per line: {"input": text, "utf8_hex": hex of the
// canonical form's UTF-8 bytes}. The test file stores these outputs as
// literals; rerun this script to regenerate/verify them.
"use strict";

////////////////////////////////////////////////////////////
// RFC 8785 Appendix A, verbatim below this line.          //
////////////////////////////////////////////////////////////
var canonicalize = function(object) {

    var buffer = '';
    serialize(object);
    return buffer;

    function serialize(object) {
        if (object === null || typeof object !== 'object' ||
            object.toJSON != null) {
            /////////////////////////////////////////////////
            // Primitive type or toJSON, use "JSON"        //
            /////////////////////////////////////////////////
            buffer += JSON.stringify(object);

        } else if (Array.isArray(object)) {
            /////////////////////////////////////////////////
            // Array - Maintain element order              //
            /////////////////////////////////////////////////
            buffer += '[';
            let next = false;
            object.forEach((element) => {
                if (next) {
                    buffer += ',';
                }
                next = true;
                /////////////////////////////////////////
                // Array element - Recursive expansion //
                /////////////////////////////////////////
                serialize(element);
            });
            buffer += ']';

        } else {
            /////////////////////////////////////////////////
            // Object - Sort properties before serializing //
            /////////////////////////////////////////////////
            buffer += '{';
            let next = false;
            Object.keys(object).sort().forEach((property) => {
                if (next) {
                    buffer += ',';
                }
                next = true;
                /////////////////////////////////////////////
                // Property names are strings, use "JSON"  //
                /////////////////////////////////////////////
                buffer += JSON.stringify(property);
                buffer += ':';
                //////////////////////////////////////////
                // Property value - Recursive expansion //
                //////////////////////////////////////////
                serialize(object[property]);
            });
            buffer += '}';
        }
    }
};
////////////////////////////////////////////////////////////
// End of RFC 8785 Appendix A.                             //
////////////////////////////////////////////////////////////

const inputs = JSON.parse(require("fs").readFileSync(0, "utf8"));
for (const text of inputs) {
    const out = canonicalize(JSON.parse(text));
    process.stdout.write(JSON.stringify({input: text, utf8_hex: Buffer.from(out, "utf8").toString("hex")}) + "\n");
}
