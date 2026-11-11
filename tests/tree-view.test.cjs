'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const E=require('../web/repertoire-training/editor-model.js');
const {esc,routeNode,treeHtml}=require('../web/repertoire-training/tree-view.js');

function fixture(){
  return{root_id:'root',goal_plies:8,nodes:[
    {id:'root',parent_id:null,ply:0},
    {id:'prefix',parent_id:'root',ply:1,name:'Shared prefix',enabled:true},
    {id:'alpha',parent_id:'prefix',ply:2,name:'First choice',enabled:true},
    {id:'alpha-cont',parent_id:'alpha',ply:3,name:'First continuation',enabled:true},
    {id:'gamma',parent_id:'alpha-cont',ply:4,name:'Nested first',enabled:true},
    {id:'delta',parent_id:'alpha-cont',ply:4,name:'Nested second',enabled:true},
    {id:'beta',parent_id:'prefix',ply:2,name:'Second choice',enabled:true},
    {id:'beta-cont',parent_id:'beta',ply:3,name:'Second continuation',enabled:true}]};
}

// A small test-only token tree verifies nesting, without a browser or package.
// It handles the renderer's quoted attributes, text and void input elements.
function parse(html){
  const root={tag:'document',attrs:{},children:[]},stack=[root];
  for(const token of html.match(/<[^>]+>|[^<]+/g)||[]){
    if(!token.startsWith('<')){stack.at(-1).children.push(token);continue;}
    const match=token.match(/^<(\/)?([a-z]+)\b([^>]*)>/i);
    assert.ok(match,'Unexpected renderer token');
    const [,closing,tag,attributes]=match;
    if(closing){assert.equal(stack.pop().tag,tag);continue;}
    const attrs={};
    for(const item of attributes.matchAll(/([\w-]+)(?:="([^"]*)")?/g))attrs[item[1]]=item[2]??'';
    const node={tag,attrs,children:[],parent:stack.at(-1)};
    node.parent.children.push(node);if(tag!=='input')stack.push(node);
  }
  assert.equal(stack.length,1,'Unbalanced renderer HTML');return root;
}
const hasClass=(node,name)=>(node.attrs?.class||'').split(/\s+/).includes(name);
function all(node,predicate){return(node.children||[]).filter(child=>typeof child!=='string').flatMap(child=>[...(predicate(child)?[child]:[]),...all(child,predicate)]);}
const findNode=(root,id)=>all(root,node=>node.attrs['data-tree-node']===id)[0];
const text=node=>(node.children||[]).map(child=>typeof child==='string'?child:text(child)).join('');

test('shared prefix and each actual path node occur once',()=>{
  const view=fixture(),root=parse(treeHtml(view,E,'all'));
  for(const node of view.nodes)assert.equal(all(root,item=>item.tag==='button'&&item.attrs['data-editor-node']===node.id).length,1);
  assert.equal(all(root,node=>hasClass(node,'tree-fork')).length,2);
});

test('same-parent choices share one sibling list and separate branch wrappers',()=>{
  const root=parse(treeHtml(fixture(),E,'all')),alpha=findNode(root,'alpha'),beta=findNode(root,'beta');
  assert.equal(alpha.parent,beta.parent);assert.ok(hasClass(alpha.parent,'tree-fork'));
  assert.ok(hasClass(alpha,'tree-option'));assert.ok(hasClass(beta,'tree-option'));
  assert.equal(alpha.attrs['data-tree-parent'],'prefix');assert.equal(beta.attrs['data-tree-parent'],'prefix');
  const siblings=alpha.parent.children.filter(node=>typeof node!=='string'&&hasClass(node,'tree-option'));
  assert.deepEqual(siblings.map(node=>node.attrs['data-tree-node']),['alpha','beta']);
});

test('deep continuation stays inside its choice body and outside the next sibling',()=>{
  const root=parse(treeHtml(fixture(),E,'all')),alpha=findNode(root,'alpha'),beta=findNode(root,'beta');
  const body=alpha.children.find(node=>typeof node!=='string'&&hasClass(node,'tree-option-body'));
  assert.ok(body);assert.ok(findNode(body,'alpha-cont'));assert.ok(findNode(body,'gamma'));assert.ok(findNode(body,'delta'));
  assert.equal(findNode(body,'beta'),undefined);assert.equal(findNode(beta,'alpha-cont'),undefined);
  const betaBody=beta.children.find(node=>typeof node!=='string'&&hasClass(node,'tree-option-body'));
  assert.ok(findNode(betaBody,'beta-cont'));
});

test('sibling alternatives show 1/2 and 2/2 independently at each fork',()=>{
  const root=parse(treeHtml(fixture(),E,'all'));
  for(const [id,number] of [['alpha','1/2'],['beta','2/2'],['gamma','1/2'],['delta','2/2']]){
    const row=findNode(root,id).children[0];
    const badges=all(row,node=>hasClass(node,'tree-choice-number'));
    assert.equal(badges.length,1);assert.equal(text(badges[0]),number);
  }
});

test('manual fold retains hidden descendants and does not change source data',()=>{
  const view=fixture(),before=structuredClone(view),collapsed=new Set(['alpha']);
  const root=parse(treeHtml(view,E,'all',collapsed)),alpha=findNode(root,'alpha');
  const body=alpha.children.find(node=>typeof node!=='string'&&hasClass(node,'tree-option-body'));
  assert.ok(Object.hasOwn(body.attrs,'hidden'));assert.ok(findNode(body,'alpha-cont'));assert.ok(findNode(body,'gamma'));
  const fold=all(alpha,node=>node.attrs['data-editor-fold']==='alpha')[0];
  assert.equal(fold.attrs['aria-expanded'],'false');
  assert.ok(all(alpha,node=>hasClass(node,'tree-collapsed-count')).some(node=>text(node).includes('3')));
  assert.deepEqual(view,before);assert.deepEqual([...collapsed],['alpha']);
  const reopened=parse(treeHtml(view,E,'all',new Set()));
  const reopenedBody=findNode(reopened,'alpha').children.find(node=>typeof node!=='string'&&hasClass(node,'tree-option-body'));
  assert.equal(Object.hasOwn(reopenedBody.attrs,'hidden'),false);
});

test('unselected prefix remains visible on an included downstream path',()=>{
  const view=fixture();view.nodes.find(node=>node.id==='prefix').enabled=false;
  const root=parse(treeHtml(view,E,'included')),prefix=findNode(root,'prefix');
  assert.ok(prefix);assert.ok(all(prefix,node=>hasClass(node,'route-node')&&hasClass(node,'draft')).length);
  assert.ok(findNode(root,'alpha'));assert.ok(findNode(root,'beta'));
});

test('identical names under different parents remain distinct actual paths',()=>{
  const view=fixture();for(const id of ['alpha-cont','beta-cont'])view.nodes.find(node=>node.id===id).name='Repeated name';
  const root=parse(treeHtml(view,E,'all')),first=findNode(root,'alpha-cont'),second=findNode(root,'beta-cont');
  assert.ok(first);assert.ok(second);assert.notEqual(first.parent,second.parent);
  assert.equal(first.attrs['data-tree-parent'],'alpha');assert.equal(second.attrs['data-tree-parent'],'beta');
  assert.equal(all(root,node=>node.tag==='b'&&text(node)==='Repeated name').length,2);
});

test('names and identifiers are HTML escaped before entering text or attributes',()=>{
  const dangerous='<img src=x onerror="alert(1)"> & \'',id='choice" data-injected="yes';
  const html=routeNode({id,ply:1,name:dangerous,enabled:false});
  assert.ok(html.includes('&lt;img'));assert.ok(html.includes('&quot;'));assert.ok(html.includes('&amp;'));assert.ok(html.includes('&#39;'));
  const root=parse(html);assert.equal(all(root,node=>node.tag==='img').length,0);
  assert.equal(all(root,node=>Object.hasOwn(node.attrs,'data-injected')).length,0);
  assert.equal(esc('&<>"\''),'&amp;&lt;&gt;&quot;&#39;');
});
