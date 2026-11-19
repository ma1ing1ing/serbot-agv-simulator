// Joint animation only. World positions and pursuit are computed by the engine.
export const channels = ['rightHip','leftHip','rightKnee','leftKnee',
  'rightShoulder','leftShoulder','rightElbow','leftElbow','lean'];

export function validateMotionPack(pack) {
  if(pack?.schema_version!==1 || pack.method!=='projected-2d-joint-angles' ||
     JSON.stringify(pack.channels)!==JSON.stringify(channels)) throw new Error('지원하지 않는 모션 형식');
  for(const kind of ['walk','jog','run']) {
    const clip=pack.clips?.[kind];
    if(!clip || !Number.isFinite(clip.duration_seconds) || clip.duration_seconds<=0 ||
       !Array.isArray(clip.samples) || clip.samples.length<8 ||
       !clip.samples.every(row=>Array.isArray(row)&&row.length===channels.length&&row.every(Number.isFinite)))
      throw new Error('모션 데이터가 올바르지 않습니다');
  }
  return pack;
}

export function sampleMotion(pack, kind, time) {
  const clip=pack?.clips?.[kind];
  if(!clip) return fallbackMotion(kind,time);
  const phase=((time/clip.duration_seconds)%1+1)%1*clip.samples.length;
  const index=Math.floor(phase), next=(index+1)%clip.samples.length, t=phase-index;
  const values=clip.samples[index].map((v,j)=>v*(1-t)+clip.samples[next][j]*t);
  // Retarget the observed variations around the character's own neutral hips.
  // This gain and the bend constraints are artistic 3-D approximations.
  for(const j of [0,1,4,5]) {
    const mean=clip.samples.reduce((sum,row)=>sum+row[j],0)/clip.samples.length;
    values[j]=(values[j]-mean)*(j<2?1.7:1.5);
  }
  values[2]=Math.max(0,Math.min(2.1,values[2]));
  values[3]=Math.max(0,Math.min(2.1,values[3]));
  return values;
}

export function fallbackMotion(kind,time) {
  const run=kind==='run', jog=kind==='jog', phase=time*(run?9:jog?7.5:6);
  const stride=Math.sin(phase)*(run?.65:jog?.5:.32);
  return [stride,-stride,Math.max(0,Math.sin(phase+1))*(run?1.2:.55),
    Math.max(0,Math.sin(phase+1+Math.PI))*(run?1.2:.55),
    -stride*.8,stride*.8,run?-1:-.25,run?-1:-.25,run?.12:0];
}
