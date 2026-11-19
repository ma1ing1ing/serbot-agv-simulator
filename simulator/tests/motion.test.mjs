import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {sampleMotion,validateMotionPack,channels} from '../static/motion.js';

test('invalid motion arrays cannot introduce NaN into the renderer',()=>{
  assert.throws(()=>validateMotionPack({schema_version:1}));
  assert(sampleMotion(null,'run',0).every(Number.isFinite));
});

let pack;
try {pack=JSON.parse(await readFile(new URL('../static/motions/childact.local.json',import.meta.url),'utf8'));}
catch(error) {if(error.code!=='ENOENT')throw error;}

test('locally built ChildACT loops have finite poses and continuous wraparound',{skip:!pack},()=>{
  validateMotionPack(pack);
  assert.equal(pack.assumptions.metric_trajectory_available,false);
  for(const kind of ['walk','jog','run']) {
    const clip=pack.clips[kind];
    assert(clip.source_end_frame>clip.source_start_frame);
    const first=sampleMotion(pack,kind,0),wrapped=sampleMotion(pack,kind,clip.duration_seconds);
    assert.deepEqual(first,wrapped);
    let variation=0;
    for(let i=0;i<120;i++) {
      const pose=sampleMotion(pack,kind,i/120*clip.duration_seconds);
      assert.equal(pose.length,channels.length);
      assert(pose.every(Number.isFinite));
      assert(pose[2]>=0 && pose[3]>=0);
      variation+=Math.abs(pose[0]-first[0]);
    }
    assert(variation>1,'actual source motion must vary over the loop');
  }
});
