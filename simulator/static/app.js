import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';

const $ = (s) => document.querySelector(s);
const dom = Object.fromEntries(['viewport','camera-view','children-list','logs','pose','heading','velocity','sim-time','front-distance','camera-status','camera-fps','connection'].map(id => [id, document.getElementById(id)]));
let state = null, publisher = '', view = 'orbit', lastPoll = 0, lastUpload = 0, uploadBusy = false;
let published = 0, fpsStart = performance.now(), lastSpeech = 0, toastTimer, childIds = '', logSignature = '';
const childModels = new Map();
let scene, renderer, sensorRenderer, camera, sensorCamera, controls, robot, pathLine, fovGroup, robotScreen;
let ready = false;

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
  for(const x of [-4.5,4.5]) {
    box(scene,.7,.38,1.6,'#c5a984',x,.19,.5);
    box(scene,.73,.10,1.63,'#dbc9a8',x,.44,.5);
    box(scene,.16,.5,1.6,'#c3a681',x+(x<0?-.27:.27),.58,.5);
  }
  for(const [x,z] of [[-5,3.9],[5,3.9]]) {
    cylinder(scene,.23,.18,.35,'#c6ac84',x,.175,z);
    cylinder(scene,.03,.03,.65,'#73835f',x,.55,z);
    for(let i=0;i<7;i++) {
      const leaf=sphere(scene,.23,'#879d6d',x+Math.sin(i*2.4)*.2,.7+(i%3)*.12,z+Math.cos(i*2.4)*.17);
      leaf.scale.set(.6,1.2,.7);leaf.rotation.z=i;
    }
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
  const scale=child.height/1.2;group.scale.setScalar(scale);
  // Local +z is the child's face. Each limb rotates about a real shoulder/hip.
  const torso=box(group,.30,.36,.19,shirt,0,.66,0);torso.geometry.computeVertexNormals();
  cylinder(group,.045,.05,.09,skin,0,.89,0);
  const head=sphere(group,.145,skin,0,1.045,0);head.scale.set(.94,1.05,.92);
  const haircap=mesh(new THREE.SphereGeometry(.149,20,12,0,Math.PI*2,0,Math.PI*.53),hair,group,0,1.055,0);
  if(child.id%2===0) {
    for(const x of [-.14,.14]) sphere(group,.055,hair,x,1.035,-.04);
  } else {box(group,.24,.065,.11,hair,0,1.12,.06);}
  for(const x of [-.048,.048]) sphere(group,.011,'#363b32',x,1.053,.126);
  sphere(group,.014,'#d79d77',0,1.02,.139);
  box(group,.045,.007,.009,'#ab735b',0,.988,.135);
  const arms=[],legs=[];
  for(const side of [-1,1]) {
    const arm=new THREE.Group();arm.position.set(side*.20,.8,0);group.add(arm);
    const sleeve=box(arm,.105,.16,.13,shirt,0,-.055,0);sleeve.rotation.z=side*.08;
    cylinder(arm,.041,.035,.19,skin,0,-.22,0);sphere(arm,.043,skin,0,-.32,0);arms.push(arm);
    const leg=new THREE.Group();leg.position.set(side*.085,.48,0);group.add(leg);
    box(leg,.115,.19,.15,pants,0,-.075,0);
    cylinder(leg,.041,.032,.22,skin,0,-.265,0);
    box(leg,.11,.07,.18,shoe,0,-.395,.026);legs.push(leg);
  }
  const name=label(child.name);name.position.y=1.4/scale;group.add(name);
  const shadow=mesh(new THREE.CircleGeometry(.23,24),new THREE.MeshBasicMaterial({color:'#71816a',transparent:true,opacity:.12,depthWrite:false}),group,0,.012,0);shadow.rotation.x=-Math.PI/2;
  group.userData={arms,legs};scene.add(group);return group;
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
  robot.position.set(state.robot.x,0,state.robot.z);robot.rotation.y=-state.robot.heading;
  for(const child of state.children) {
    let model=childModels.get(child.id);
    if(!model) {model=createChild(child);childModels.set(child.id,model);}
    model.position.set(child.x,0,child.z);model.rotation.y=child.heading;
    const stride=child.moving?Math.sin(state.time*(child.running?13:child.pace*15)+child.phase)*(child.running?.8:.5):0;
    model.userData.legs.forEach((l,i)=>l.rotation.x=(i?1:-1)*stride);
    model.userData.arms.forEach((a,i)=>{a.rotation.x=(i?-1:1)*stride*.8;a.rotation.z=child.wave?(i?-1:1)*(.7+Math.sin(state.time*7)*.25):0;});
    if(child.wave) model.rotation.y+=Math.sin(state.time*5+child.phase)*.16;
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
function animate(now) {
  requestAnimationFrame(animate);
  if(!ready) return;
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
    state=await api('/api/state');
    dom.connection.classList.remove('offline');dom.connection.innerHTML='<i></i> 로컬 시뮬레이터 연결됨';
    updateWorld();updateUI();
  } catch(e) {dom.connection.classList.add('offline');dom.connection.innerHTML='<i></i> 서버 연결 끊김';dom['camera-status'].textContent='연결 끊김';}
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
  const allWatched=state.children.every(c=>c.watched);
  $('#people-count').disabled=phase==='approaching'||phase==='escaping';
  $('#game-card').dataset.phase=phase;
  $('#game-stage').textContent=({ready:'게임 대기',approaching:game.held?'접근 일시정지':allWatched?'로봇 시선 · 정지':'로봇 뒤쪽에서 접근',escaping:'터치! 모두 도망',finished:'한 게임 완료'})[phase];
  $('#game-title').textContent=({ready:'시선에 따라 접근 · 정지',approaching:game.held?'접근 일시정지':allWatched?'아이들 정지':'아이들 접근',escaping:`아이 ${game.touched_by+1} 터치 · 전원 도망`,finished:'전원 출발선 도착'})[phase];
  $('#game-detail').textContent=({ready:'로봇이 뒤돌면 접근, 바라보면 정지. 한 명이 터치하면 전원 도망.',approaching:'로봇 전방에 있는 아이는 멈추고, 뒤쪽에 있는 아이만 접근합니다.',escaping:`전원 도망 중 · 출발선 도착 ${game.escaped_ids.length}/${state.children.length}명`,finished:`아이 ${game.touched_by+1} 터치 · 새 게임으로 다시 시작`})[phase];
  $('#game-start').textContent=phase==='ready'?'게임 시작':'새 게임';
  $('#game-hold').disabled=phase!=='approaching';
  $('#game-hold').textContent=game.held?'접근 계속하기':'접근 잠깐 멈춤';
  document.querySelectorAll('[data-step]').forEach(el=>el.classList.toggle('active',el.dataset.step===phase));
  const announcement=$('#game-announcement');announcement.hidden=phase!=='escaping'&&phase!=='finished';
  announcement.classList.toggle('finished',phase==='finished');
  announcement.textContent=phase==='escaping'?`아이 ${game.touched_by+1} 터치! 모두 출발선으로 도망가요!`:'전원 출발선 도착 · 게임 완료';
  if(document.activeElement!==$('#rate')) $('#rate').value=state.rate;
  const ids=state.children.map(c=>c.id).join(',');
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
      el.disabled=phase==='escaping'||phase==='finished';
      el.querySelector('[value="walk"]').textContent=phase==='escaping'?'도망가기':phase==='approaching'&&c.watched?'시선 · 멈춤':'걷기';
      el.querySelector('[value="still"]').textContent=c.escaped?'출발선 도착':'멈춤';
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
}
$('#pause').addEventListener('click',()=>state&&act('/api/world/config',{paused:!state.paused}));
$('#reset').addEventListener('click',()=>{lastSpeech=-1;act('/api/world/reset',{});if('speechSynthesis' in window)speechSynthesis.cancel();});
$('#rate').addEventListener('change',e=>act('/api/world/config',{rate:Number(e.target.value)}));
$('#people-count').addEventListener('input',e=>$('#people-value').textContent=e.target.value+'명');
$('#people-count').addEventListener('change',e=>act('/api/world/config',{count:Number(e.target.value)}));
$('#game-start').addEventListener('click',()=>act('/api/game/start',{}));
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
  init3d();await poll();
} catch(e) {$('#loading').innerHTML='';$('#loading').textContent='시뮬레이터를 시작하지 못했습니다: '+e.message;console.error(e);}
