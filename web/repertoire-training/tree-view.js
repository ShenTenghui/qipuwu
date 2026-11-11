'use strict';

// Exact selected production functions; host supplies the route model.
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  function routeNode(node,choice){return'<div class="route-node '+(node.enabled?'included':'draft')+'"><button data-editor-node="'+esc(node.id)+'" data-node-mark="'+esc(node.id)+'"><span class="route-ply">'+Math.ceil(node.ply/2)+(node.ply%2?'红':'黑')+'</span><b>'+esc(node.name||node.move)+'</b>'+(choice?'<span class="tree-choice-number" title="此局面的第 '+choice.index+' 种选择，共 '+choice.total+' 种">'+choice.index+'/'+choice.total+'</span>':'')+'</button><label title="将这着纳入训练"><input type="checkbox" aria-label="将第'+node.ply+'着'+esc(node.name||node.move)+'纳入训练" data-editor-node-toggle="'+esc(node.id)+'" '+(node.enabled?'checked':'')+'><span>'+(node.enabled?'已纳入':'草稿')+'</span></label></div>';}

  function treeHtml(view,E,filter='included',collapsed=new Set()){
    const visible=new Set(E.routes(view,filter).flatMap(route=>route.nodes.map(node=>node.id))),children=new Map();
    for(const node of view.nodes||[]){if(node.parent_id&&(filter==='all'||visible.has(node.id))){if(!children.has(node.parent_id))children.set(node.parent_id,[]);children.get(node.parent_id).push(node);}}
    const counts=new Map(),count=id=>{if(!counts.has(id))counts.set(id,(children.get(id)||[]).reduce((sum,node)=>sum+1+count(node.id),0));return counts.get(id);};
    const branch=id=>{
      const siblings=children.get(id)||[],fork=siblings.length>1;
      const ply=siblings[0]?.ply,choiceLabel=ply?Math.ceil(ply/2)+(ply%2?'红':'黑')+' · ':'';
      return'<ul class="'+(fork?'tree-fork':'tree-sequence')+'"'+(collapsed.has(id)?' hidden':'')+'>'+(fork?'<li class="tree-fork-label">'+choiceLabel+'同一步的 '+siblings.length+' 种选择</li>':'')+siblings.map((node,index)=>{
        const hasChildren=!!children.get(node.id)?.length,folded=collapsed.has(node.id),descendants=hasChildren?count(node.id):0;
        const row='<div class="tree-row'+(fork?' tree-option-head':'')+'">'+(hasChildren?'<button class="tree-fold" data-editor-fold="'+esc(node.id)+'" aria-expanded="'+!folded+'" aria-label="'+(folded?'展开':'收起')+esc(node.name||node.move)+'后的 '+descendants+' 着">'+(folded?'▸':'▾')+'</button>':'<span class="tree-fold-space"></span>')+routeNode(node,fork?{index:index+1,total:siblings.length}:null)+(folded?'<span class="tree-collapsed-count">已收起 '+descendants+' 着</span>':node.terminal||node.ply===view.goal_plies?'<span class="tree-end">终点</span>':'')+'</div>';
        const continuation=hasChildren?branch(node.id):'';
        return'<li class="'+(fork?'tree-option':'tree-step')+'" data-tree-node="'+esc(node.id)+'" data-tree-parent="'+esc(id)+'">'+row+(fork&&hasChildren?'<div class="tree-option-body"'+(folded?' hidden':'')+'>'+continuation+'</div>':continuation)+'</li>';
      }).join('')+'</ul>';
    };
    return'<div class="tree-root"><button class="route-origin" data-editor-node="'+esc(view.root_id)+'" data-node-mark="'+esc(view.root_id)+'">起点</button></div>'+branch(view.root_id);
  }

module.exports={esc,routeNode,treeHtml};
