'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {Controller}=require('../web/repertoire-training/editor-model.js');

function fixture(wrap){
  const calls=[],data=new Map();let revision=1,node='root',serial=0;
  const view=()=>({id:'synthetic',revision,title:'Synthetic recording',goal_plies:4,
    root_id:'root',current:{id:node,fen:'9/9/9/9/9/9/9/9/9/9 w',legal_moves:['a3a4'],history:[]},nodes:[]});
  const base=async(path,body)=>{
    calls.push({path,body:body&&structuredClone(body)});
    if(path==='editor_catalog')return{drafts:[]};
    if(path.startsWith('editor_recommendations'))return{draft_id:'synthetic',node_id:node,revision,status:'ready',groups:[]};
    if(path.startsWith('editor?'))return view();
    if(path==='editor_record'){revision++;node='child';return view();}
    return view();
  };
  const api=wrap?wrap(base):base;
  const storage={getItem:key=>data.get(key)||null,setItem:(key,value)=>data.set(key,value),removeItem:key=>data.delete(key)};
  return{calls,data,controller:new Controller(api,()=>{},{automaticRecommendations:false,storage,newId:()=> 'synthetic-'+(++serial)})};
}

test('opening reads references without requesting computation',async()=>{
  const f=fixture();await f.controller.open('synthetic');
  await new Promise(resolve=>setImmediate(resolve));
  assert.ok(f.calls.some(value=>value.path.startsWith('editor_recommendations?')));
  assert.equal(f.calls.some(value=>value.path==='editor_recommendations'),false);
});

test('recording a move does not choose training inclusion',async()=>{
  const f=fixture();await f.controller.open('synthetic');await f.controller.record('a3a4');
  const sent=f.calls.find(value=>value.path==='editor_record').body;
  assert.equal(sent.move,'a3a4');assert.equal(sent.revision,1);
  assert.equal(Object.hasOwn(sent,'enabled'),false);
  assert.equal(f.controller.state.view.current.id,'child');
});

test('illegal selection in the controller never submits a move',async()=>{
  const f=fixture();await f.controller.open('synthetic');await f.controller.record('a0a9');
  assert.equal(f.calls.some(value=>value.path==='editor_record'),false);
});

test('lost mutation response preserves the exact replay body',async()=>{
  let fail=true;
  const f=fixture(base=>async(path,body)=>{
    if(path==='editor_record'&&fail){fail=false;throw new Error('synthetic disconnect');}
    return base(path,body);
  });
  await f.controller.open('synthetic');await f.controller.record('a3a4');
  const pending=structuredClone(f.controller.state.pending);
  assert.equal(pending.path,'editor_record');
  await f.controller.retry();
  assert.equal(f.calls.find(value=>value.path==='editor_record').body.request_id,pending.body.request_id);
  assert.equal(f.controller.state.pending,null);
});

test('leaving does not start calculations or retain polling',async()=>{
  const f=fixture();await f.controller.open('synthetic');f.controller.leave();
  assert.equal(f.controller.visible,false);
  assert.equal(f.controller.timer,null);
  assert.equal(f.calls.some(value=>value.path==='editor_recommendations'),false);
});


test('automatic references read a cache before posting once for a missing context',async()=>{
  const calls=[],timers=new Map();let next=0;
  const view={id:'synthetic',revision:1,current:{id:'root',fen:'9/9/9/9/9/9/9/9/9/9 w'},nodes:[]};
  const c=new Controller(async(path,body)=>{
    calls.push({path,body});if(path.startsWith('editor?'))return view;
    return{draft_id:'synthetic',node_id:'root',revision:1,status:path==='editor_recommendations'?'queued':'idle',primary:{status:'empty'}};
  },()=>{},{schedule:fn=>{const id=++next;timers.set(id,fn);return id;},cancel:id=>timers.delete(id)});
  await c.open('synthetic');await new Promise(resolve=>setImmediate(resolve));
  assert.ok(calls.findIndex(v=>v.path.includes('?'))<calls.findIndex(v=>v.path==='editor_recommendations'));
  assert.equal(calls.filter(v=>v.path==='editor_recommendations').length,1);
  await c.loadRecommendations();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(calls.filter(v=>v.path==='editor_recommendations').length,1);c.leave();
});

test('verified references do not request a new calculation',async()=>{
  const calls=[];const c=new Controller(async(path)=>{
    calls.push(path);if(path.startsWith('editor?'))return{id:'synthetic',revision:1,current:{id:'root',fen:'9/9/9/9/9/9/9/9/9/9 w'}};
    return{draft_id:'synthetic',node_id:'root',revision:1,status:'ready',primary:{status:'verified'}};
  });
  await c.open('synthetic');await new Promise(resolve=>setImmediate(resolve));assert.equal(calls.includes('editor_recommendations'),false);c.leave();
});

test('automatic refinement keeps polling until ready and leaving cancels its timer',async()=>{
  const timers=new Map();let next=0;
  const c=new Controller(async(path)=>path.startsWith('editor?')?{id:'synthetic',revision:1,current:{id:'root',fen:'9/9/9/9/9/9/9/9/9/9 w'}}:
    {draft_id:'synthetic',node_id:'root',revision:1,status:'ready',primary:{status:'verified'},automatic:{status:'paused'}},()=>{},
    {schedule:fn=>{const id=++next;timers.set(id,fn);return id;},cancel:id=>timers.delete(id)});
  await c.open('synthetic');await new Promise(resolve=>setImmediate(resolve));assert.equal(timers.size,1);c.leave();assert.equal(timers.size,0);
});
