/* Character Studio v0.15.1 — CSS pixel to character-local [0,1] transform.
 * Standalone, no DOM or network dependencies. Usable by Node tests or the
 * current Windows WebView2 stage via <script src="..."></script>.
 *
 * Build the SAME mapping the renderer used to draw the character. Do not
 * infer touch regions from viewport percentages: scene zoom, movement,
 * mirror and contain/cover crop change the inverse transform.
 */
(function (root, factory) {
    "use strict";
    const api = factory();
    if (typeof module === "object" && module.exports) module.exports = api;
    if (root) root.CharacterTouchGeometry = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
    "use strict";

    function finite(value, label) {
        if (typeof value !== "number" || !Number.isFinite(value)) {
            throw new TypeError(label + " must be a finite number");
        }
        return value;
    }

    function positive(value, label) {
        const x = finite(value, label);
        if (x <= 0) throw new RangeError(label + " must be positive");
        return x;
    }

    function optionalNumber(value, fallback, label) {
        return value == null ? fallback : finite(value, label);
    }

    function imageMatrixFromLayout(options) {
        if (!options || typeof options !== "object") {
            throw new TypeError("layout options required");
        }
        const rect = options.rect;
        if (!rect || typeof rect !== "object") {
            throw new TypeError("viewport element rect required");
        }
        const left = finite(rect.left, "left");
        const top = finite(rect.top, "top");
        const width = positive(rect.width, "viewport width");
        const height = positive(rect.height, "viewport height");
        const sourceWidth = positive(options.sourceWidth, "sourceWidth");
        const sourceHeight = positive(options.sourceHeight, "sourceHeight");
        const fit = options.fit || "contain";
        if (fit !== "contain" && fit !== "cover" && fit !== "fill") {
            throw new RangeError("invalid object fit");
        }
        let scaleX = width / sourceWidth;
        let scaleY = height / sourceHeight;
        if (fit !== "fill") {
            const scale = fit === "contain"
                ? Math.min(scaleX, scaleY)
                : Math.max(scaleX, scaleY);
            scaleX = scale;
            scaleY = scale;
        }
        const drawWidth = sourceWidth * scaleX;
        const drawHeight = sourceHeight * scaleY;
        const zoom = positive(optionalNumber(options.zoom, 1, "zoom"), "zoom");
        const panX = optionalNumber(options.panX, 0, "panX");
        const panY = optionalNumber(options.panY, 0, "panY");
        const rotationDeg = optionalNumber(options.rotationDeg, 0, "rotationDeg");
        const flipX = options.flipX === undefined ? false : options.flipX;
        if (typeof flipX !== "boolean") throw new TypeError("flipX must be boolean");
        const radians = rotationDeg * Math.PI / 180;
        const cos = Math.cos(radians);
        const sin = Math.sin(radians);
        const direction = flipX ? -1 : 1;
        const centerX = left + width / 2 + panX;
        const centerY = top + height / 2 + panY;
        // Screen CSS px = [a*x + c*y + e, b*x + d*y + f] for
        // a local (x,y) whose [0,0] and [1,1] bound the native character image.
        const a = direction * drawWidth * zoom * cos;
        const b = direction * drawWidth * zoom * sin;
        const c = -drawHeight * zoom * sin;
        const d = drawHeight * zoom * cos;
        return {
            a, b, c, d,
            e: centerX - (a + c) / 2,
            f: centerY - (b + d) / 2
        };
    }

    function affineValues(matrix) {
        if (!matrix || typeof matrix !== "object") {
            throw new TypeError("affine matrix is required");
        }
        for (const key of ["a", "b", "c", "d", "e", "f"]) {
            finite(matrix[key], key);
        }
        return matrix;
    }

    function mapPoint(matrix, x, y) {
        affineValues(matrix);
        finite(x, "x");
        finite(y, "y");
        return {
            x: matrix.a * x + matrix.c * y + matrix.e,
            y: matrix.b * x + matrix.d * y + matrix.f
        };
    }

    function invertPoint(matrix, clientX, clientY) {
        affineValues(matrix);
        finite(clientX, "clientX");
        finite(clientY, "clientY");
        const det = matrix.a * matrix.d - matrix.b * matrix.c;
        if (!Number.isFinite(det) || Math.abs(det) < 1e-9) {
            throw new RangeError("singular character transform");
        }
        const dx = clientX - matrix.e;
        const dy = clientY - matrix.f;
        return {
            x: (matrix.d * dx - matrix.c * dy) / det,
            y: (-matrix.b * dx + matrix.a * dy) / det
        };
    }

    function normalizedPointer(matrix, clientX, clientY, options) {
        const o = options || {};
        if (o.overlayBlocked === true || o.characterVisible === false) {
            return null;
        }
        if (o.rect) {
            const r = o.rect;
            const left = finite(r.left, "stage left");
            const top = finite(r.top, "stage top");
            const w = positive(r.width, "stage width");
            const h = positive(r.height, "stage height");
            if (clientX < left || clientX > left + w ||
                clientY < top || clientY > top + h) {
                return null;
            }
        }
        const point = invertPoint(matrix, clientX, clientY);
        const epsilon = 1e-8;
        if (point.x < -epsilon || point.x > 1 + epsilon ||
            point.y < -epsilon || point.y > 1 + epsilon) {
            return null;
        }
        // Remove tiny floating-point noise only, never clamp an outside click.
        return {
            x: Math.min(1, Math.max(0, point.x)),
            y: Math.min(1, Math.max(0, point.y))
        };
    }

    return Object.freeze({
        imageMatrixFromLayout,
        mapPoint,
        invertPoint,
        normalizedPointer
    });
});
