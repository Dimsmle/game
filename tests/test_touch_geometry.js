/* Node contract tests; no browser, image or local resource needed. */
"use strict";
const assert = require("node:assert/strict");
const G = require("../studio/web/touch_geometry.js");

function close(a,b) {
    assert.ok(Math.abs(a-b) < 1e-8, `${a} != ${b}`);
}
function verify(options, point) {
    const mat=G.imageMatrixFromLayout(options);
    const screen=G.mapPoint(mat,point.x,point.y);
    const actual=G.normalizedPointer(mat,screen.x,screen.y,{rect:options.rect});
    assert.ok(actual,"point should be inside clip");
    close(actual.x,point.x);
    close(actual.y,point.y);
}

const rect={left:120,top:60,width:440,height:600};
verify({rect,sourceWidth:1024,sourceHeight:2048,fit:"contain"}, {x:.23,y:.77});
verify({rect,sourceWidth:2048,sourceHeight:1024,fit:"contain"}, {x:.23,y:.77});
verify({rect,sourceWidth:1024,sourceHeight:2048,fit:"cover"}, {x:.23,y:.77});
verify({rect,sourceWidth:1024,sourceHeight:2048,fit:"fill"}, {x:.23,y:.77});
verify({rect,sourceWidth:1024,sourceHeight:2048,zoom:1.5}, {x:.23,y:.77});
verify({rect,sourceWidth:1024,sourceHeight:2048,panX:15,panY:-20}, {x:.23,y:.77});
verify({rect,sourceWidth:1024,sourceHeight:2048,flipX:true}, {x:.23,y:.77});
verify({rect,sourceWidth:1024,sourceHeight:2048,rotationDeg:30}, {x:.23,y:.77});
verify({rect,sourceWidth:1024,sourceHeight:2048,rotationDeg:60,flipX:true,
    zoom:.8,panX:12,panY:6}, {x:.23,y:.77});
const mirror=G.imageMatrixFromLayout({rect,sourceWidth:440,sourceHeight:600,flipX:true});
const rightSide=G.mapPoint(mirror,.1,.2);
close(G.invertPoint(mirror,rightSide.x,rightSide.y).x,.1);
assert.equal(G.normalizedPointer(mirror,0,0,{rect}),null);
assert.equal(G.normalizedPointer(mirror,rightSide.x,rightSide.y,{rect,overlayBlocked:true}),null);
assert.equal(G.normalizedPointer(mirror,rightSide.x,rightSide.y,{rect,characterVisible:false}),null);
const identity={a:1,b:0,c:0,d:1,e:0,f:0};
assert.equal(G.normalizedPointer(identity,1.2,.5),null,"outside local image");
assert.deepEqual(G.normalizedPointer(identity,.5,.5),{x:.5,y:.5});
assert.throws(()=>G.invertPoint({a:0,b:0,c:0,d:0,e:0,f:0},1,1),/singular/);
assert.throws(()=>G.imageMatrixFromLayout({rect,sourceWidth:0,sourceHeight:40}),/positive/);
assert.throws(()=>G.imageMatrixFromLayout({rect,sourceWidth:30,sourceHeight:40,fit:"stretchy"}),/fit/);
assert.throws(()=>G.imageMatrixFromLayout({rect,sourceWidth:30,sourceHeight:40,zoom:Infinity}),/finite/);
assert.throws(()=>G.imageMatrixFromLayout({rect,sourceWidth:30,sourceHeight:40,flipX:"yes"}),/boolean/);
let seed = 20261015;
function rand() {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296;
}
for (let index = 0; index < 300; index++) {
    const stage = {
        left: rand() * 200 - 100,
        top: rand() * 200 - 100,
        width: 300 + rand() * 1000,
        height: 300 + rand() * 1000
    };
    const opts = {
        rect: stage,
        sourceWidth: 300 + rand() * 1800,
        sourceHeight: 400 + rand() * 1800,
        zoom: 0.6 + rand() * 1.7,
        panX: rand() * 200 - 100,
        panY: rand() * 150 - 75,
        rotationDeg: rand() * 360 - 180,
        flipX: rand() < .5,
        fit: ["contain", "cover", "fill"][Math.floor(rand() * 3)]
    };
    const matrix = G.imageMatrixFromLayout(opts);
    const native = {x: .1 + rand() * .8, y: .1 + rand() * .8};
    const screen = G.mapPoint(matrix, native.x, native.y);
    const reverted = G.invertPoint(matrix, screen.x, screen.y);
    close(reverted.x, native.x);
    close(reverted.y, native.y);
}
console.log("PASS: 18 fixed + 300 randomized geometry checks (rotation, mirror, zoom, pan, cropping)");
