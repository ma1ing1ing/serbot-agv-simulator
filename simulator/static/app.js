import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';
import {sampleMotion, validateMotionPack} from './motion.js';
import {redLightCues, RedLightVoice} from './red-light-sounds.js';

const $ = (s) => document.querySelector(s);
const dom = Object.fromEntries(['viewport','camera-view','children-list','logs','pose','heading','velocity','sim-time','front-distance','camera-status','camera-fps','connection'].map(id => [id, document.getElementById(id)]));
let state = null, publisher = '', view = 'orbit', lastPoll = 0, lastUpload = 0, uploadBusy = false;
let published = 0, fpsStart = performance.now(), lastSpeech = 0, toastTimer, childIds = '', logSignature = '';
const childModels = new Map();
const childPaths = new Map();
const obstacleModels = new Map();
let obstacleSignature='';
let scene, renderer, sensorRenderer, camera, sensorCamera, controls, robot, pathLine, fovGroup, robotScreen;
let ready = false;
let motionPack=null, stateReceivedAt=0, lastAnimationAt=0;
let replayInfo=null, renderedEpoch='', renderedRevision=-1;
let syncRenderer=null, syncCamera=null, syncSize='', syncBusy=false, syncDone='';

const gameVoice = new RedLightVoice();
const soundToggle = $('#red-light-sound');

function soundUnavailable() {
  gameVoice.stop();
  soundToggle.checked = false;
  toast('놀이 소리를 재생할 수 없어요. 놀이 소리를 다시 켜 주세요.');
}

function enableGameSound() {
  if (soundToggle.checked && $('#game-mode').value === 'red_light') {
    gameVoice.enable().catch(soundUnavailable);
  }
}
soundToggle.addEventListener('change', () => {
  if (soundToggle.checked) enableGameSound();
  else gameVoice.stop();
});
// A user gesture unlocks audio, including when an API client started the game.
document.addEventListener('click', enableGameSound);
document.addEventListener('visibilitychange', () => { if (document.hidden) gameVoice.stop(); });

async function loadReplay() {
  try {replayInfo=await api('/api/replay');}
  catch {replayInfo={available:false,error:'위치 기록을 확인하지 못했습니다'};}
  const select=$('#replay-clip');select.replaceChildren();
  for(const clip of replayInfo.clips||[]) select.add(new Option(clip.name,clip.id));
  $('#replay-status').textContent=replayInfo.available?`${replayInfo.participants}명 위치 기록 연결됨`:'위치 기록 파일을 먼저 준비해 주세요';
  $('#replay-status').title=replayInfo.error||'';
}

async function loadMotions() {
  try {
    const response=await fetch('/motions/childact.local.json');
    if(!response.ok) throw new Error('local motions unavailable');
    motionPack=validateMotionPack(await response.json());
    $('#motion-status').textContent='ChildACT 동작 연결됨';
    $('#motion-status').dataset.source='childact';
  } catch {
    $('#motion-status').textContent='기본 동작 사용 중';
    $('#motion-status').dataset.source='procedural';
  }
}

async function api(path, data) {
  const response = await fetch(path, data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
}
function toast(text) {
  $('#toast').textContent=text; $('#toast').hidden=false;
  clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('#toast').hidden=true,3500);
}
async function act(path,data) { try { await api(path,data); await poll(); } catch(e) { toast(e.message); } }
const mat = (color, extra={}) => new THREE.MeshStandardMaterial({color,roughness:.8,...extra});
function mesh(geometry, material, parent, x=0,y=0,z=0) {
  const object=new THREE.Mesh(geometry,material); object.position.set(x,y,z);
  object.castShadow=true; object.receiveShadow=true; parent.add(object); return object;
}
function box(parent,w,h,d,color,x=0,y=0,z=0) { return mesh(new THREE.BoxGeometry(w,h,d),typeof color==='string'?mat(color):color,parent,x,y,z); }
function sphere(parent,r,color,x=0,y=0,z=0) { return mesh(new THREE.SphereGeometry(r,20,14),typeof color==='string'?mat(color):color,parent,x,y,z); }
function cylinder(parent,rt,rb,h,color,x=0,y=0,z=0) { return mesh(new THREE.CylinderGeometry(rt,rb,h,24),typeof color==='string'?mat(color):color,parent,x,y,z); }
function canvasTexture(w,h,draw) {
  const c=document.createElement('canvas'); c.width=w;c.height=h;
  const ctx=c.getContext('2d'); draw(ctx,w,h);
  const texture=new THREE.CanvasTexture(c);texture.colorSpace=THREE.SRGBColorSpace;
  return {texture,canvas:c,ctx};
}
function sign(text,width=512,height=128,bg='#e5ebd9',fg='#58705a') {
  return canvasTexture(width,height,(c,w,h)=>{c.fillStyle=bg;c.fillRect(0,0,w,h);c.fillStyle=fg;c.font=`600 ${Math.round(h*.4)}px sans-serif`;c.textAlign='center';c.textBaseline='middle';c.fillText(text,w/2,h/2);}).texture;
}
function label(text) {
  const sprite=new THREE.Sprite(new THREE.SpriteMaterial({map:sign(text,256,80,'#f6f7ec','#648168'),transparent:true,depthTest:false}));
  sprite.scale.set(.57,.18,1);sprite.layers.set(1); return sprite;
}
function createRoom() {
  const floor=mat('#e1dfca');
  box(scene,11.6,.12,9.8,floor,0,-.07,0);
  const grid=new THREE.GridHelper(11,22,'#c6cdb8','#d4d8c3');grid.position.y=.002;grid.scale.z=9/11;scene.add(grid);
  const playmat=mesh(new THREE.PlaneGeometry(7.2,6.7),mat('#c3d6bd'),scene,0,.008,.2);playmat.rotation.x=-Math.PI/2;
  const innerGrid=new THREE.GridHelper(6,12,'#b9cdb2','#bdd0b5');innerGrid.position.set(0,.012,.25);scene.add(innerGrid);
  for(const z of [-2.1,3.2]) box(scene,7.2,.007,.045,'#f6f6df',0,.018,z);
  for(let i=0;i<5;i++) {
    const marker=cylinder(scene,.24,.24,.008,['#ecc786','#e8dad1','#aec4cb','#e6c6aa','#d1cae0'][i],(i-2)*.95,.022,3.15);
    marker.receiveShadow=true;
  }
  const wallmat=mat('#f6f2e2');
  const back=mesh(new THREE.PlaneGeometry(11.6,3.6),wallmat,scene,0,1.8,4.6);back.rotation.y=Math.PI;
  const left=mesh(new THREE.PlaneGeometry(9.8,3.6),wallmat,scene,-5.6,1.8,0);left.rotation.y=Math.PI/2;
  const right=mesh(new THREE.PlaneGeometry(9.8,3.6),wallmat,scene,5.6,1.8,0);right.rotation.y=-Math.PI/2;
  // Wall decorations use one-sided planes so the external orbit camera sees inside.
  const border=mat('#b5c5a6');
  const skirting=mesh(new THREE.PlaneGeometry(11.6,.6),border,scene,0,.3,4.58);skirting.rotation.y=Math.PI;
  const poster=mesh(new THREE.PlaneGeometry(3.8,.95),new THREE.MeshBasicMaterial({map:sign('LET’S PLAY!',768,192,'#e8e2c6','#6e8b66')}),scene,0,2.1,4.57);poster.rotation.y=Math.PI;
  for(const x of [-3.4,3.4]) {
    const windowmat=new THREE.MeshBasicMaterial({color:'#c9dedb'});
    const win=mesh(new THREE.PlaneGeometry(1.35,1.3),windowmat,scene,x,2.15,4.57);win.rotation.y=Math.PI;
    // Place muntins on the interior side; they are visible from the robot camera.
    box(scene,1.42,.05,.04,'#fdf9e9',x,2.15,4.53);
    box(scene,.05,1.36,.04,'#fdf9e9',x,2.15,4.53);
  }
  const rug=cylinder(scene,.9,.9,.006,'#e8d9b2',0,.014,-3.35);rug.receiveShadow=true;
}
function createRobot() {
  const group=new THREE.Group();scene.add(group);
  const dark=mat('#354640'), yellow=mat('#ebba4e'), black=mat('#283530');
  box(group,.66,.21,.74,yellow,0,.28,0);
  box(group,.67,.075,.76,dark,0,.16,0);
  box(group,.57,.07,.65,'#f1ca69',0,.43,0);
  const wheels=[];
  for(const x of [-.35,.35]) {
    const wheel=cylinder(group,.15,.15,.09,black,x,.16,0);wheel.rotation.z=Math.PI/2;wheels.push(wheel);
    const hub=cylinder(group,.075,.075,.095,'#a9ada3',x,.16,0);hub.rotation.z=Math.PI/2;
  }
  for(const z of [-.28,.28]) {const caster=cylinder(group,.055,.055,.05,black,0,.065,z);caster.rotation.z=Math.PI/2;}
  const column=new THREE.Group();column.position.set(0,.73,-.055);column.rotation.x=-.12;group.add(column);
  box(column,.53,.62,.17,yellow);
  box(column,.55,.42,.06,dark,0,.055,.115);
  robotScreen=canvasTexture(512,384,drawFace);
  mesh(new THREE.PlaneGeometry(.49,.35),new THREE.MeshBasicMaterial({map:robotScreen.texture}),column,0,.055,.148);
  box(group,.56,.055,.37,dark,0,1.065,-.04);
  cylinder(group,.1,.1,.065,black,0,1.12,-.04);
  cylinder(group,.09,.09,.035,'#586555',0,1.169,-.04);
  box(group,.09,.055,.035,black,0,1.04,.16);
  const lens=cylinder(group,.018,.018,.014,'#537787',0,1.04,.185);lens.rotation.x=Math.PI/2;
  for(const x of [-.18,.18]) {
    cylinder(group,.009,.009,.22,black,x,1.19,-.14);
    sphere(group,.011,'#526252',x,1.305,-.14);
  }
  for(const x of [-.20,.20]) {const s=cylinder(group,.026,.026,.025,'#9fa9a0',x,.28,.381);s.rotation.x=Math.PI/2;}
  const name=label('SERBOT AGV');name.position.y=1.55;group.add(name);
  group.userData.wheels=wheels;
  return group;
}
function drawFace(ctx,w,h) {
  ctx.fillStyle='#263f38';ctx.fillRect(0,0,w,h);
  ctx.fillStyle='#d5e3bf';
  for(const x of [w*.34,w*.66]) {ctx.beginPath();ctx.ellipse(x,h*.38,15,23,0,0,Math.PI*2);ctx.fill();}
  ctx.strokeStyle='#d5e3bf';ctx.lineWidth=9;ctx.lineCap='round';ctx.beginPath();ctx.arc(w*.5,h*.43,w*.15,.24,Math.PI-.24);ctx.stroke();
  ctx.font='500 23px sans-serif';ctx.textAlign='center';ctx.fillStyle='#8fae92';ctx.fillText('SERBOT · SIM',w/2,h*.85);
}
function createChild(child) {
  const group=new THREE.Group(),skin=mat('#e7b890'),hair=mat('#4a3a2f'),shirt=mat(child.color),pants=mat('#586d79'),shoe=mat('#f4eee0');
  const scale=child.height/1.2*(child.display_scale||1);group.scale.setScalar(scale);
  // Local +z is the child's face. Each limb rotates about a real shoulder/hip.
  const body=new THREE.Group();body.position.y=.48;group.add(body);
  const torso=box(body,.30,.36,.19,shirt,0,.18,0);torso.geometry.computeVertexNormals();
  cylinder(body,.045,.05,.09,skin,0,.41,0);
  const head=sphere(body,.145,skin,0,.565,0);head.scale.set(.94,1.05,.92);
  const haircap=mesh(new THREE.SphereGeometry(.149,20,12,0,Math.PI*2,0,Math.PI*.53),hair,body,0,.575,0);
  if(child.id%2===0) {
    for(const x of [-.14,.14]) sphere(body,.055,hair,x,.555,-.04);
  } else {box(body,.24,.065,.11,hair,0,.64,.06);}
  for(const x of [-.048,.048]) sphere(body,.011,'#363b32',x,.573,.126);
  sphere(body,.014,'#d79d77',0,.54,.139);
  box(body,.045,.007,.009,'#ab735b',0,.508,.135);
  const arms=[],legs=[],elbows=[],knees=[],feet=[];
  for(const side of [-1,1]) {
    const arm=new THREE.Group();arm.position.set(side*.20,.32,0);body.add(arm);
    const sleeve=box(arm,.105,.16,.13,shirt,0,-.055,0);sleeve.rotation.z=side*.08;
    cylinder(arm,.041,.037,.12,skin,0,-.115,0);
    const elbow=new THREE.Group();elbow.position.y=-.18;arm.add(elbow);
    sphere(elbow,.039,skin);cylinder(elbow,.036,.03,.14,skin,0,-.07,0);sphere(elbow,.041,skin,0,-.16,0);
    arms.push(arm);elbows.push(elbow);
    const leg=new THREE.Group();leg.position.set(side*.085,.48,0);group.add(leg);
    box(leg,.115,.19,.15,pants,0,-.075,0);
    const knee=new THREE.Group();knee.position.y=-.205;leg.add(knee);
    sphere(knee,.042,skin);cylinder(knee,.039,.031,.17,skin,0,-.085,0);
    const foot=new THREE.Group();foot.position.set(0,-.195,.026);knee.add(foot);
    box(foot,.11,.07,.18,shoe);legs.push(leg);knees.push(knee);feet.push(foot);
  }
  const name=label(child.name);name.position.y=1.4/scale;group.add(name);
  const shadow=mesh(new THREE.CircleGeometry(.23,24),new THREE.MeshBasicMaterial({color:'#71816a',transparent:true,opacity:.12,depthWrite:false}),group,0,.012,0);shadow.rotation.x=-Math.PI/2;
  const caughtRing=mesh(new THREE.RingGeometry(.25,.29,32),new THREE.MeshBasicMaterial({color:'#ce7b66',side:THREE.DoubleSide}),group,0,.023,0);
  caughtRing.rotation.x=-Math.PI/2;caughtRing.visible=false;
  group.userData={arms,legs,elbows,knees,feet,body,shadow,caughtRing,pose:Array(9).fill(0)};
  group.position.set(child.x,0,child.z);group.rotation.y=child.heading;
  scene.add(group);return group;
}
function createFov() {
  const group=new THREE.Group();scene.add(group);
  const geo=new THREE.BufferGeometry();
  geo.setAttribute('position',new THREE.Float32BufferAttribute([0,.028,0,-2.9,.028,4.1,2.9,.028,4.1],3));
  const wedge=mesh(geo,new THREE.MeshBasicMaterial({color:'#d5c078',transparent:true,opacity:.13,side:THREE.DoubleSide,depthWrite:false}),group);
  wedge.layers.set(1);
  const lines=new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0,.03,0),new THREE.Vector3(-2.9,.03,4.1),new THREE.Vector3(0,.03,0),new THREE.Vector3(2.9,.03,4.1)]),new THREE.LineBasicMaterial({color:'#bda466',transparent:true,opacity:.4}));
  lines.layers.set(1);group.add(lines);return group;
}
function init3d() {
  scene=new THREE.Scene();scene.background=new THREE.Color('#e8ede3');scene.fog=new THREE.Fog('#e8ede3',20,45);
  renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));
  renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;renderer.outputColorSpace=THREE.SRGBColorSpace;
  renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.23;dom.viewport.prepend(renderer.domElement);
  sensorRenderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});sensorRenderer.setSize(640,480,false);sensorRenderer.setPixelRatio(1);
  sensorRenderer.shadowMap.enabled=true;sensorRenderer.shadowMap.type=THREE.PCFSoftShadowMap;sensorRenderer.outputColorSpace=THREE.SRGBColorSpace;
  sensorRenderer.toneMapping=THREE.ACESFilmicToneMapping;sensorRenderer.toneMappingExposure=1.23;dom['camera-view'].append(sensorRenderer.domElement);
  camera=new THREE.PerspectiveCamera(43,1,.05,80);camera.position.set(9,9,10);camera.layers.enable(1);
  sensorCamera=new THREE.PerspectiveCamera(75,4/3,.05,40);
  controls=new OrbitControls(camera,renderer.domElement);controls.target.set(0,.25,0);controls.enableDamping=true;controls.minDistance=3;controls.maxDistance=24;controls.maxPolarAngle=Math.PI/2-.05;
  scene.add(new THREE.HemisphereLight('#fff9e7','#96ae91',2.4));
  const sun=new THREE.DirectionalLight('#fff2d5',3.2);sun.position.set(-3,10,-4);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);
  Object.assign(sun.shadow.camera,{left:-8,right:8,top:8,bottom:-8,near:.5,far:25});sun.shadow.bias=-.0004;sun.shadow.normalBias=.035;scene.add(sun);
  createRoom();robot=createRobot();fovGroup=createFov();
  pathLine=new THREE.Line(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:'#567b5d',transparent:true,opacity:.7}));pathLine.layers.set(1);scene.add(pathLine);
  new ResizeObserver(()=>{const w=dom.viewport.clientWidth,h=dom.viewport.clientHeight;renderer.setSize(w,h);camera.aspect=w/h;camera.updateProjectionMatrix();}).observe(dom.viewport);
  renderer.domElement.addEventListener('webglcontextlost',e=>{e.preventDefault();ready=false;$('#loading').hidden=false;$('#loading').textContent='3D 그래픽 연결이 끊겼습니다. 페이지를 새로고침해 주세요.';});
  ready=true;$('#loading').hidden=true;requestAnimationFrame(animate);
}
function setView(mode) {
  view=mode;controls.enabled=mode==='orbit';
  if(mode==='robot') camera.layers.disable(1);else camera.layers.enable(1);
  document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('selected',b.dataset.view===mode));
  if(mode==='orbit') {camera.position.set(9,9,10);controls.target.set(0,.25,0);camera.up.set(0,1,0);controls.update();}
  if(mode==='top') {camera.position.set(0,17,.01);camera.up.set(0,0,-1);camera.lookAt(0,0,0);}
  $('#view-hint').textContent=({orbit:'드래그로 회전 · 스크롤로 확대',top:'위에서 보는 전체 공간',robot:'로봇에 장착된 카메라 시점'})[mode];
}
function updateWorld() {
  if(!state||!ready) return;
  updateObstacles();
  const revision=state.replay?.revision??-1;
  const discontinuity=renderedEpoch!==state.epoch||renderedRevision!==revision;
  if(discontinuity) {
    for(const model of childModels.values()) {scene.remove(model);dispose(model);}
    childModels.clear();
    for(const line of childPaths.values()) {scene.remove(line);dispose(line);}
    childPaths.clear();
    renderedEpoch=state.epoch;renderedRevision=revision;
  }
  robot.position.set(state.robot.x,0,state.robot.z);robot.rotation.y=-state.robot.heading;
  for(const child of state.children) {
    let model=childModels.get(child.id);
    if(!model) {model=createChild(child);childModels.set(child.id,model);}
    model.visible=child.visible!==false;
    model.userData.caughtRing.visible=Boolean(child.caught);
    model.userData.caughtRing.material.color.set(child.state==='frozen'?'#509ddd':'#dc655e');
    if(state.replay) {
      let line=childPaths.get(child.id);
      if(!line) {line=new THREE.Line(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:child.color,transparent:true,opacity:.8}));line.layers.set(1);scene.add(line);childPaths.set(child.id,line);}
      const points=(child.trail||[]).map(([x,z])=>new THREE.Vector3(x,.037,z));
      line.geometry.dispose();line.geometry=new THREE.BufferGeometry().setFromPoints(points);
      line.visible=$('#show-path').checked&&child.visible!==false&&points.length>1;
    }
  }
  for(const [id,model] of childModels) if(!state.children.some(c=>c.id===id)) {scene.remove(model);dispose(model);childModels.delete(id);}
  const points=state.trail.map(([x,z])=>new THREE.Vector3(x,.025,z));
  const old=pathLine.geometry;pathLine.geometry=new THREE.BufferGeometry().setFromPoints(points.length>1?points:[...points,...points]);old.dispose();
  pathLine.visible=$('#show-path').checked;
  fovGroup.position.copy(robot.position);fovGroup.rotation.y=robot.rotation.y;fovGroup.visible=$('#show-fov').checked;
  robot.updateMatrixWorld(true);
  const eye=robot.localToWorld(new THREE.Vector3(0,1.04,.22));
  const target=robot.localToWorld(new THREE.Vector3(0,.94,6));
  sensorCamera.position.copy(eye);sensorCamera.lookAt(target);
  if(view==='robot') {camera.position.copy(eye);camera.up.set(0,1,0);camera.lookAt(target);camera.fov=75;camera.updateProjectionMatrix();}
  else if(camera.fov!==43) {camera.fov=43;camera.updateProjectionMatrix();}
}
function updateObstacles() {
  const obstacles=state.obstacles||[];
  const signature=JSON.stringify(obstacles.map(({x,z,w,d})=>[x,z,w,d]));
  if(signature===obstacleSignature) return;
  for(const model of obstacleModels.values()) {scene.remove(model);dispose(model);}
  obstacleModels.clear();obstacleSignature=signature;
  obstacles.forEach((obstacle,index)=>{
    const group=new THREE.Group();group.position.set(obstacle.x,0,obstacle.z);
    // The visible footprint matches the rectangle used by physics and sensors.
    box(group,obstacle.w,.6,obstacle.d,'#c5a984',0,.3,0);
    box(group,obstacle.w,.08,obstacle.d,'#dbc9a8',0,.64,0);
    scene.add(group);obstacleModels.set(index,group);
  });
}
const footPosition=new THREE.Vector3();
function animateChildren(now) {
  if(!state) return;
  const dt=Math.min(.1,Math.max(0,(now-lastAnimationAt)/1000));lastAnimationAt=now;
  const stepped=state.execution_mode==='stepped';
  const elapsed=state.paused||stepped?0:Math.min(.12,Math.max(0,(now-stateReceivedAt)/1000))*state.rate;
  const alpha=state.paused||stepped?1:1-Math.exp(-dt*18);
  for(const child of state.children) {
    const model=childModels.get(child.id);if(!model) continue;
    if(child.visible===false) continue;
    model.position.x+=(child.x-model.position.x)*alpha;
    model.position.z+=(child.z-model.position.z)*alpha;
    const turn=Math.atan2(Math.sin(child.heading-model.rotation.y),Math.cos(child.heading-model.rotation.y));
    model.rotation.y+=turn*alpha;
    const kind=child.motion_kind==='run'||child.running?'run':child.motion_kind==='jog'?'jog':'walk';
    const time=(child.motion_time!==undefined||state.replay)&&state.game.phase!=='ready'?child.motion_time+(child.moving?elapsed*(child.speed/(kind==='run'?.85:kind==='jog'?.62:.44)):0):state.time+elapsed+child.phase;
    const target=child.moving?sampleMotion(motionPack,kind,time):[0,0,.05,.05,0,0,-.15,-.15,0];
    const rig=model.userData;
    rig.pose=rig.pose.map((v,j)=>v+(target[j]-v)*alpha);
    for(let i=0;i<2;i++) {
      rig.legs[i].rotation.x=rig.pose[i];rig.knees[i].rotation.x=rig.pose[i+2];
      rig.arms[i].rotation.x=rig.pose[i+4];rig.elbows[i].rotation.x=rig.pose[i+6];
      rig.arms[i].rotation.z=child.wave?(i?-1:1)*(.7+Math.sin(time*7)*.25):0;
    }
    rig.body.rotation.x=rig.pose[8];
    // Ground the lowest shoe; depth, foot contact and timing are approximations.
    model.position.y=0;model.updateMatrixWorld(true);
    let lowest=Infinity;
    for(const foot of rig.feet) {foot.getWorldPosition(footPosition);lowest=Math.min(lowest,footPosition.y-.035*model.scale.y);}
    model.position.y=Math.max(-.03,.025-lowest);
    rig.shadow.position.y=(.012-model.position.y)/model.scale.y;
    rig.caughtRing.position.y=(.023-model.position.y)/model.scale.y;
  }
}
function dispose(group) {group.traverse(o=>{o.geometry?.dispose();const ms=Array.isArray(o.material)?o.material:[o.material];for(const m of ms)if(m){m.map?.dispose();m.dispose();}});}
async function publishFrame(now) {
  if(uploadBusy||!state||!publisher||!ready||now-lastUpload<125) return;
  uploadBusy=true;lastUpload=now;
  const epoch=state.epoch, simTime=state.time;
  try {
    robot.visible=false;sensorRenderer.render(scene,sensorCamera);robot.visible=true;
    const blob=await new Promise(resolve=>sensorRenderer.domElement.toBlob(resolve,'image/jpeg',.84));
    if(blob) {
      const response=await fetch('/api/camera/frame',{method:'POST',headers:{'Content-Type':'image/jpeg','X-Publisher':publisher,'X-Sim-Time':String(simTime),'X-Epoch':epoch},body:blob});
      if(response.ok) published++;
      else if(response.status!==409) throw new Error('카메라 업로드 실패');
    }
    if(now-fpsStart>2000){dom['camera-fps'].textContent=`${(published*1000/(now-fpsStart)).toFixed(1)} fps`;published=0;fpsStart=now;}
  } catch(e) {dom['camera-status'].textContent='영상 연결 확인';}
  finally {robot.visible=true;uploadBusy=false;}
}
// Opt-in tick-synchronized frame (GET /api/camera/sync.jpg). The server lists a pending request in
// /api/state; this tab renders it only from a snapshot of exactly that tick (stepped or paused world,
// so children snap to the state without interpolation) and uploads it with the request id.
async function publishSyncFrame(snapshot) {
  const request=snapshot.camera_sync;
  if(!request||request.id===syncDone||syncBusy||uploadBusy||!ready||!publisher) return;
  if(request.epoch!==snapshot.epoch||request.tick!==request.state_tick) return;
  if(snapshot.execution_mode!=='stepped'&&!snapshot.paused) return;
  syncBusy=true;
  try {
    animateChildren(performance.now());
    if(!syncRenderer) {
      syncRenderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});syncRenderer.setPixelRatio(1);
      syncRenderer.shadowMap.enabled=true;syncRenderer.shadowMap.type=THREE.PCFSoftShadowMap;syncRenderer.outputColorSpace=THREE.SRGBColorSpace;
      syncRenderer.toneMapping=THREE.ACESFilmicToneMapping;syncRenderer.toneMappingExposure=1.23;
      syncCamera=new THREE.PerspectiveCamera(75,4/3,.05,40);
    }
    const size=`${request.width}x${request.height}@${request.fov}`;
    if(size!==syncSize) {
      syncRenderer.setSize(request.width,request.height,false);
      syncCamera.aspect=request.width/request.height;syncCamera.fov=request.fov;syncCamera.updateProjectionMatrix();syncSize=size;
    }
    syncCamera.position.copy(sensorCamera.position);syncCamera.quaternion.copy(sensorCamera.quaternion);
    robot.visible=false;syncRenderer.render(scene,syncCamera);robot.visible=true;
    const blob=await new Promise(resolve=>syncRenderer.domElement.toBlob(resolve,'image/jpeg',.92));
    if(blob) {
      const response=await fetch('/api/camera/frame',{method:'POST',headers:{'Content-Type':'image/jpeg','X-Publisher':publisher,
        'X-Sim-Time':String(snapshot.time),'X-Epoch':snapshot.epoch,'X-Sim-Tick':String(request.tick),'X-Sync-ID':request.id},body:blob});
      if(response.ok||response.status===409) syncDone=request.id;
    }
  } catch(e) {dom['camera-status'].textContent='동기 영상 확인';}
  finally {robot.visible=true;syncBusy=false;}
}
function animate(now) {
  requestAnimationFrame(animate);
  if(!ready) return;
  animateChildren(now);
  if(view==='orbit') controls.update();
  const hide=view==='robot';robot.visible=!hide;renderer.render(scene,camera);robot.visible=true;
  if(now-lastPoll>65) {lastPoll=now;poll();}
  publishFrame(now);
}
let polling=false;
async function poll() {
  if(polling) return;
  polling=true;
  try {
    const previous=state;
    state=await api('/api/state');
    const fresh=performance.now()-stateReceivedAt<1500 && !dom.connection.classList.contains('offline');
    stateReceivedAt=performance.now();
    if(state.epoch!==previous?.epoch) gameVoice.stop();
    if(state.epoch!==previous?.epoch&&state.game.phase!=='ready') {
      $('#game-mode').value=state.game.mode;
      const behaviors=new Set(state.children.map(child=>child.behavior_type).filter(Boolean));
      $('#child-behavior').value=behaviors.size===1?[...behaviors][0]:'mixed';
      if(Number.isInteger(state.game.seed)) $('#game-seed').value=state.game.seed;
    }
    dom.connection.classList.remove('offline');dom.connection.innerHTML='<i></i> 로컬 시뮬레이터 연결됨';
    const quiet = state.game.gaze_timing === 'friendly' && (state.game.phase === 'finished' ||
      state.game.phase === 'ready' || state.game.held || state.paused || state.game.tracking_lost);
    if (quiet) gameVoice.stop();
    else if (soundToggle.checked && !document.hidden && fresh) {
      const cues = redLightCues(previous, state);
      if (cues.length) gameVoice.play(cues, state.game.friendly_cue_gain ?? 1).catch(soundUnavailable);
    }
    updateWorld();updateUI();
    if(state.camera_sync) publishSyncFrame(state);
  } catch(e) {gameVoice.stop();dom.connection.classList.add('offline');dom.connection.innerHTML='<i></i> 서버 연결 끊김';dom['camera-status'].textContent='연결 끊김';}
  finally {polling=false;}
}
function updateUI() {
  const r=state.robot;
  dom.pose.innerHTML=`${r.x.toFixed(2)} / ${r.z.toFixed(2)} <em>m</em>`;
  dom.heading.innerHTML=`${(r.heading*180/Math.PI).toFixed(1)} <em>°</em>`;
  dom.velocity.innerHTML=`${r.linear.toFixed(2)} <em>m/s</em>`;
  const mins=Math.floor(state.time/60),secs=(state.time%60).toFixed(1).padStart(4,'0');dom['sim-time'].textContent=`${String(mins).padStart(2,'0')}:${secs}`;
  dom['front-distance'].innerHTML=`${state.ultrasonic.front_min_cm.toFixed(0)} <em>cm</em>`;
  $('#paused-badge').hidden=!state.paused;
  $('#pause span').textContent=state.paused?'계속 실행':'일시정지';$('#pause use').setAttribute('href',state.paused?'#i-play':'#i-pause');
  dom['camera-status'].textContent=state.camera.ready?'LIVE':'준비 중';
  if(document.activeElement!==$('#people-count')) $('#people-count').value=state.children.length;
  $('#people-value').textContent=state.children.length+'명';
  const game=state.game, phase=game.phase;
  const selected=phase==='ready'?$('#game-mode').value:game.mode;
  const isTag=selected==='tag';
  const isReplay=selected==='playground_a';
  const active=['approaching','escaping','chasing','replaying'].includes(phase);
  const names={tag:'술래잡기',freeze_tag:'얼음땡',red_light:'무궁화꽃이 피었습니다'};
  const details={tag:'로봇을 피해 도망갑니다. 잡히면 멈춥니다.',freeze_tag:'잡히면 얼음! 친구가 가까이 머무르면 다시 움직여요.',red_light:'로봇이 출발선 쪽을 바라보면 정지하고, 등을 돌리면 접근합니다. 첫 터치에 출발선으로 달아납니다.'};
  const stages={ready:'게임 대기',chasing:'놀이 진행 중',approaching:'접근 · 시선 정지',escaping:'터치 후 추격',finished:'게임 완료'};
  $('#people-count').disabled=active||isReplay;
  $('#people-count').max=isReplay?16:8;
  $('.range-ticks span:last-child').textContent=isReplay?'16명':'8명';
  $('#game-mode').disabled=active;
  $('#auto-chase-control').hidden=isReplay;
  $('#auto-chase').disabled=false;
  if(active&&!isReplay) $('#auto-chase').checked=game.auto_chase;
  $('#gaze-options').hidden=(active?game.mode:$('#game-mode').value)!=='red_light';
  $('#gaze-timing').disabled=active;
  const learnedTiming = $('#gaze-timing').value === 'friendly';
  if (learnedTiming && !active) $('#turn-profile').value='smooth';
  $('#turn-profile').disabled=active||learnedTiming||state.execution_mode==='stepped';
  $('#stop-reaction').disabled=active;
  if(active&&game.mode==='red_light') {
    $('#gaze-timing').value=game.gaze_timing||'timed';
    $('#turn-profile').value=game.turn_profile||'baseline';
    $('#stop-reaction').value=game.stop_reaction||'immediate';
  }
  $('#game-options').hidden=isReplay;
  $('#game-seed').disabled=active;$('#game-limit').disabled=active;$('#game-record').disabled=active;
  $('#child-behavior').disabled=active;
  $('#game-finish').disabled=!active||isReplay;
  const ep=state.episode;
  $('#record-status').textContent=ep?.recording?`${ep.closed?'저장 완료':'기록 중'} · ${ep.samples}개 시점 · ${ep.directory}`:'기록 저장을 켜면 플레이를 파일로 남깁니다.';
  $('#game-card').dataset.phase=phase;
  const approachStage=phase==='approaching'&&game.mode==='red_light';
  const escort=game.escort;
  const escortStage=escort&&{pickup:'술래가 적발한 아이에게 이동 중',lead:'술래가 아이를 데려가는 중',return:'술래가 놀이 위치로 돌아오는 중'}[escort.stage];
  const stage=escortStage||(approachStage?(game.watching?'아이들 정지 신호':'아이들 접근 가능'):stages[phase]||phase);
  $('#game-stage').textContent=game.held?'놀이 잠깐 멈춤':stage;
  let counts=selected==='freeze_tag'?`얼음 ${game.frozen_ids?.length||0} / ${state.children.length}명`:`잡힘 ${game.caught_ids.length} / ${state.children.length}명`;
  if(selected==='red_light'&&game.eliminated_ids?.length) counts+=` · 적발 ${game.eliminated_ids.length}명`;
  $('#game-title').textContent=phase==='ready'?(names[selected]||'위치 기록 재생'):`${names[selected]||''} · ${counts}`;
  $('#game-detail').textContent=details[selected]||'';
  if(approachStage&&game.auto_chase&&!escort&&!game.held&&!state.paused) {
    const target=game.looking?0:Math.PI;
    const error=Math.atan2(Math.sin(target-r.heading),Math.cos(target-r.heading));
    const settled=Math.abs(error)<=.02&&Math.abs(r.angular)<=.05&&Math.abs(r.linear)<=.01;
    const motion=game.looking?(settled?'앞을 보고 관찰':'앞으로 돌아보기'):(settled?'등을 돌리고 대기':'뒤돌기');
    $('#game-detail').textContent=`로봇 동작 · ${motion}`;
  }
  $('#game-start').textContent=phase==='ready'?'게임 시작':'새 게임';
  $('#game-start').disabled=false;
  $('#game-hold').disabled=!active;
  $('#game-hold').textContent=game.held?'놀이 계속하기':'놀이 잠깐 멈춤';
  const labels=selected==='freeze_tag'?['① 도망','② 얼음 · 구조','③ 전원 얼음']:selected==='red_light'?['① 접근 · 정지','② 터치 · 도망','③ 추격 종료']:['① 도망','② 잡힘','③ 전원 잡힘'];
  document.querySelectorAll('[data-step]').forEach((el,i)=>{el.textContent=labels[i];el.classList.toggle('active',i===(phase==='finished'?2:phase==='escaping'?1:0));});
  $('#game-helper').textContent='아이마다 속도·반응 시간·체력·구조 성향이 달라요.';
  $('#game-note').textContent='자동 제어는 위치를 아는 규칙 시연입니다. 수동 주행이나 Python 명령을 보내면 해제됩니다.';
  const reasons={all_caught:'모두 잡았습니다',all_frozen:'모두 얼음 상태입니다',time_limit:'제한 시간이 끝났습니다',pursuit_complete:'추격이 끝났습니다',all_eliminated:'모두 탈락했습니다',user_stopped:'게임을 종료했습니다'};
  const announcement=$('#game-announcement');announcement.hidden=phase!=='escaping'&&phase!=='finished';
  announcement.classList.toggle('finished',phase==='finished');
  announcement.textContent=phase==='finished'?(reasons[game.end_reason]||'게임 종료'):'터치! 출발선으로 도망가요!';
  updateReplayUI(isReplay);
  if(state.replay&&$('#game-mode').value!=='playground_a') $('#game-start').textContent='선택한 놀이 시작';
  if(document.activeElement!==$('#rate')) $('#rate').value=state.rate;
  const ids=state.epoch+':'+state.children.map(c=>c.id).join(',');
  if(ids!==childIds) {
    childIds=ids;dom['children-list'].replaceChildren();
    for(const c of state.children) {
      const row=document.createElement('div');row.className='child-row';
      const dot=document.createElement('span');dot.className='child-dot';dot.style.background=c.color;
      const name=document.createElement('span');name.className='child-name';name.textContent=c.name;
      const select=document.createElement('select');select.dataset.child=c.id;select.setAttribute('aria-label',`${c.name} 행동`);
      for(const [value,text] of Object.entries({still:'멈춤',walk:'걷기',intermittent:'걷다 멈춤',wiggle:'제자리 움직임'})) select.add(new Option(text,value));
      select.addEventListener('change',()=>act('/api/children',{id:c.id,mode:select.value}));
      row.append(dot,name,select);dom['children-list'].append(row);
    }
  }
  for(const c of state.children) {
    const el=$(`[data-child="${c.id}"]`);
    if(el&&document.activeElement!==el)el.value=c.mode;
    if(el) {
      el.disabled=active||phase==='finished';
      el.querySelector('[value="walk"]').textContent=isTag&&phase!=='ready'?(c.caught?'잡힘':c.running?'달리기':c.motion_kind==='jog'?'조깅':c.resting?'잠깐 쉬기':'걷기'):phase==='escaping'?'도망가기':phase==='approaching'&&c.watched?'시선 · 멈춤':'걷기';
      el.querySelector('[value="still"]').textContent=c.escaped?'출발선 도착':'멈춤';
      el.closest('.child-row').classList.toggle('caught',Boolean(c.caught));
      const escorting=escort?.child_id===c.id&&escort.stage!=='return';
      const status=escorting?(escort.stage==='pickup'?'적발 · 대기':'술래 따라가는 중'):{free:'도망',rescuing:'구조 중',frozen:'얼음',eliminated:'탈락',caught:'잡힘',approaching:'접근',stopped:'정지',escaping:'도망',escaped:'도착'}[c.state];
      el.closest('.child-row').querySelector('.child-name').textContent=c.name+(status?' · '+status:'');
      if(state.replay) {
        el.disabled=true;
        el.querySelector('[value="walk"]').textContent=c.visible===false?'기록 없음':c.moving?'이동 중':'멈춤';
        el.closest('.child-row').classList.toggle('missing',c.visible===false);
      }
    }
  }
  const signature=JSON.stringify(state.logs);
  if(signature!==logSignature) {
    logSignature=signature;const atBottom=dom.logs.scrollHeight-dom.logs.scrollTop-dom.logs.clientHeight<35;
    dom.logs.replaceChildren();
    for(const log of [...state.logs].reverse()) {const row=document.createElement('div');row.className='log-line';const time=document.createElement('time');time.textContent=log.time.toFixed(2)+'s';const dot=document.createElement('i');const text=document.createElement('span');text.textContent=log.message;row.append(time,dot,text);dom.logs.append(row);}
    $('#log-count').textContent=state.logs.length;if(atBottom)dom.logs.scrollTop=0;
  }
  if(state.speech_id!==lastSpeech) {
    lastSpeech=state.speech_id;$('#speech').textContent=state.speech;$('#speech').hidden=!state.speech;
    if(state.speech&&$('#audio').checked&&'speechSynthesis' in window) {speechSynthesis.cancel();const utterance=new SpeechSynthesisUtterance(state.speech);utterance.lang='ko-KR';speechSynthesis.speak(utterance);}
  }
  updateExecutionMode();
}
function updateExecutionMode() {
  const stepped=state.execution_mode==='stepped';
  $('#stepped-notice').hidden=!stepped;
  $('#realtime-resume').disabled=!stepped;
  for(const id of ['reset','pause','rate']) $('#'+id).disabled=stepped;
  document.querySelectorAll('[data-jog]').forEach(button=>button.disabled=stepped);
  if(!stepped) return;
  for(const id of ['people-count','game-mode','auto-chase','game-start','game-hold','game-seed','game-limit','game-record','child-behavior','replay-clip','replay-count','replay-time']) $('#'+id).disabled=true;
  document.querySelectorAll('[data-child]').forEach(select=>select.disabled=true);
}
function updateReplayUI(selected) {
  const info=state.replay, game=state.game;
  $('#replay-controls').hidden=!selected;
  $('#replay-badge').hidden=!info;
  dom['children-list'].classList.toggle('replay-list',Boolean(info));
  for(const value of [8,16]) {
    let option=$(`#rate option[value="${value}"]`);
    if(!option) {option=new Option(`${value}× · 기록 빠르게 보기`,value);$('#rate').add(option);}
    option.hidden=!info;option.disabled=!info;
  }
  if(!selected) return;
  $('#auto-chase-control').hidden=true;
  $('#gaze-options').hidden=true;
  $('#game-start').disabled=!replayInfo?.available;
  $('#game-start').textContent=info?'기록 다시 재생':'기록 재생';
  $('#game-hold').disabled=!info||game.phase==='finished';
  $('#game-hold').textContent=game.held?'재생 계속':'재생 잠깐 멈춤';
  $('#game-mode').disabled=false;
  $('#replay-clip').disabled=false;$('#replay-count').disabled=false;
  $('#replay-time').disabled=!info;
  $('#game-stage').textContent=!info?'기록 재생 대기':game.phase==='finished'?'기록 재생 완료':game.held?'재생 잠깐 멈춤':'기록 재생 중';
  const visible=state.children.filter(c=>c.visible!==false).length;
  $('#game-title').textContent=info?`위치 기록 ${visible} / ${state.children.length}명 표시`:'아이들이 움직였던 경로를 함께 봐요';
  $('#game-detail').textContent='기록된 위치를 같은 시간축으로 재생합니다. 술래 역할과 로봇에 대한 반응은 포함하지 않습니다.';
  const steps=document.querySelectorAll('[data-step]');
  steps.forEach((el,i)=>{el.textContent=['① 구간 선택','② 기록 재생','③ 경로 관찰'][i];el.classList.toggle('active',i===1&&game.phase==='replaying');});
  $('#game-helper').textContent='아이마다 색이 같은 이동선이 표시됩니다. 위에서 보면 경로를 비교하기 좋아요.';
  $('#game-note').textContent='기록이 없는 동안에는 해당 아이를 숨깁니다. 공간 맞춤·8×로 시작하며, 재생 속도와 시간 막대를 조절할 수 있어요.';
  $('#game-announcement').hidden=game.phase!=='finished';
  $('#game-announcement').textContent='위치 기록 재생 완료 · 다시 재생할 수 있어요';
  if(info) {
    const format=t=>`${String(Math.floor(t/60)).padStart(2,'0')}:${String(Math.floor(t%60)).padStart(2,'0')}`;
    $('#replay-clock').textContent=`${format(info.elapsed)} / ${format(info.duration)}`;
    $('#replay-time').max=info.duration;
    if(document.activeElement!==$('#replay-time')) $('#replay-time').value=info.elapsed;
  }
}
$('#pause').addEventListener('click',()=>state&&act('/api/world/config',{paused:!state.paused}));
$('#reset').addEventListener('click',()=>{lastSpeech=-1;act('/api/world/reset',{});if('speechSynthesis' in window)speechSynthesis.cancel();});
$('#rate').addEventListener('change',e=>act('/api/world/config',{rate:Number(e.target.value)}));
$('#people-count').addEventListener('input',e=>$('#people-value').textContent=e.target.value+'명');
$('#people-count').addEventListener('change',e=>act('/api/world/config',{count:Number(e.target.value)}));
$('#game-start').addEventListener('click',async()=>{
  const mode=$('#game-mode').value;
  const seedInput=$('#game-seed');
  if(!seedInput.reportValidity()) return;
  const settings={time_limit:Number($('#game-limit').value),child_behavior:$('#child-behavior').value};
  if(mode==='red_light') {
    settings.gaze_timing=$('#gaze-timing').value;
    settings.turn_profile=$('#turn-profile').value;
    settings.stop_reaction=$('#stop-reaction').value;
  }
  await act('/api/game/start',{mode,auto_chase:$('#auto-chase').checked,
    replay_count:Number($('#replay-count').value),clip_id:$('#replay-clip').value||'active',
    seed:Number(seedInput.value),scenario:'open',
    settings,record:mode!=='playground_a'&&$('#game-record').checked});
  if(mode==='playground_a'&&state?.replay) setView('top');
});
$('#replay-time').addEventListener('change',e=>act('/api/replay/seek',{elapsed:Number(e.target.value)}));
$('#game-mode').addEventListener('change',()=>state&&updateUI());
$('#auto-chase').addEventListener('change',e=>{if(state&&!state.replay&&!['ready','finished'].includes(state.game.phase))act('/api/game/auto',{enabled:e.target.checked});});
$('#game-finish').addEventListener('click',()=>act('/api/game/finish',{}));
$('#realtime-resume').addEventListener('click',()=>act('/api/training/close',{}));
$('#game-hold').addEventListener('click',()=>state&&act('/api/game/hold',{held:!state.game.held}));
$('#robot-stop').addEventListener('click',()=>act('/api/robot/stop',{}));
document.querySelectorAll('[data-jog]').forEach(button=>button.addEventListener('click',()=>{const d=button.dataset.jog;act('/api/robot/command',{linear_mps:d==='forward'?.2:d==='backward'?-.2:0,angular_rps:d==='left'?1:d==='right'?-1:0,seconds:.7,guard:true});}));
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>setView(button.dataset.view)));
for(const id of ['show-path','show-fov']) $('#'+id).addEventListener('change',updateWorld);
const guide=$('#api-dialog');for(const id of ['api-open','api-details']) $('#'+id).addEventListener('click',()=>guide.showModal());
$('#api-close').addEventListener('click',()=>guide.close());guide.addEventListener('click',e=>{if(e.target===guide&&e.clientX<guide.getBoundingClientRect().left)guide.close();});
$('#copy-code').addEventListener('click',async()=>{try {await navigator.clipboard.writeText('from simulator.client import SimRobot\n\nrobot = SimRobot()\nframe = robot.camera_frame()\n# frame을 나만의 AI에 전달하고 판단 결과로 로봇을 제어하세요.\nrobot.command_velocity(linear_mps=0.1, seconds=0.5)\n');toast('Python 연결 코드를 복사했습니다');} catch {toast('복사 권한을 확인하거나 연결 가이드의 코드를 선택해 주세요.');}});
window.addEventListener('error',e=>{if(!ready){$('#loading').textContent='3D 화면을 시작하지 못했습니다. 브라우저의 WebGL 지원을 확인해 주세요.';}console.error(e.error);});
try {
  ({publisher}=await api('/api/session'));
  init3d();await Promise.all([loadMotions(),loadReplay(),poll()]);updateUI();
} catch(e) {$('#loading').innerHTML='';$('#loading').textContent='시뮬레이터를 시작하지 못했습니다: '+e.message;console.error(e);}
