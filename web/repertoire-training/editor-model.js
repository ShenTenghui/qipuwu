(function(scope){
  'use strict';
  const PENDING_KEY='qipuwu-repertoire-editor-request-v1';
  const operations=new Set(['editor_create','editor_update','editor_record','editor_toggle','editor_terminal','editor_publish']);
  function pendingValue(value){
    return value&&operations.has(value.path)&&value.body&&typeof value.body.request_id==='string'&&
      (value.path==='editor_create'||typeof value.body.id==='string')?value:null;
  }
  function scoreText(value){
    if(value?.type==='cp'&&Number.isFinite(value.cp))return(value.cp>0?'+':'')+(value.cp/100).toFixed(2);
    if(value?.type==='mate'&&Number.isInteger(value.mate_distance))return value.mate_distance===0?'已被将死':value.mate_distance>0?'可将杀 · '+value.mate_distance+'步':'被将杀 · '+Math.abs(value.mate_distance)+'步';
    return '分数未确认';
  }
  function routes(view,filter='included'){
    const nodes=view?.nodes||[],byId=new Map(nodes.map(node=>[node.id,node])),children=new Map();
    for(const node of nodes){if(node.parent_id){if(!children.has(node.parent_id))children.set(node.parent_id,[]);children.get(node.parent_id).push(node);}}
    const result=[];
    function visit(node,path){
      const next=children.get(node.id)||[],route=node.parent_id?[...path,node]:path;
      const ended=!!node.terminal||node.ply===view.goal_plies;
      if((!next.length||ended)&&route.length&&(filter==='all'||route.some(value=>value.enabled))){
        const selected=route.every(value=>value.enabled),conflict=ended&&next.some(value=>value.enabled);
        const firstSelected=route.findIndex(value=>value.enabled),draftPrefix=firstSelected>0;
        result.push({id:node.id,nodes:route,complete:selected&&ended&&!conflict,status:draftPrefix?'未连到起点 · 草稿前缀':!selected?'含未纳入着法':conflict?'终点仍有纳入后继':ended?'完整路线':'继续录制'});
      }
      for(const child of next)visit(child,route);
    }
    const root=byId.get(view?.root_id);if(root)visit(root,[]);return result;
  }
  class Controller{
    constructor(api,changed=()=>{},options={}){
      this.api=api;this.changed=changed;this.storage=options.storage||null;
      this.newId=options.newId||(()=>scope.crypto?.randomUUID?.()||'editor-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2));
      this.schedule=options.schedule||((callback,delay)=>setTimeout(callback,delay));this.cancel=options.cancel||(id=>clearTimeout(id));
      this.automaticRecommendations=options.automaticRecommendations!==false;this.automaticRequested=new Set();
      this.automaticAttempts=new Map();this.readFailures=0;this.viewAbort=null;this.onRenderError=options.onRenderError||(()=>{});
      this.visible=true;this.generation=0;this.recommendationGeneration=0;this.timer=null;this.abort=null;
      this.state={drafts:[],view:null,loading:false,busy:false,error:'',notice:'',pending:null,recommendations:null,recommendationLoading:false,recommendationBusy:false,recommendationError:''};
      try{this.state.pending=pendingValue(JSON.parse(this.storage?.getItem(PENDING_KEY)||'null'));}catch(_){}
    }
    notify(kind='editor'){try{this.changed(this.state,kind);}catch(error){try{this.onRenderError(error,kind);}catch(_){}}}
    async catalog(){try{const value=await this.api('editor_catalog');this.state.drafts=value.drafts||[];this.notify();return true;}catch(error){this.state.error=error.message;this.notify();return false;}}
    stopRecommendations(){++this.recommendationGeneration;if(this.timer!==null)this.cancel(this.timer);this.timer=null;this.abort?.abort();this.abort=null;this.state.recommendationLoading=false;this.state.recommendationBusy=false;}
    context(){const view=this.state.view;return view?{id:view.id,node_id:view.current.id,revision:view.revision}:null;}
    same(context){const now=this.context();return now&&context&&now.id===context.id&&now.node_id===context.node_id&&now.revision===context.revision;}
    accept(view){
      if(!view||typeof view.id!=='string'||!Number.isInteger(view.revision)||!view.current?.id||!view.current.fen)throw new Error('录谱回执尚未完整返回，请重试核对。');
      const previous=this.state.view;
      if(previous?.id===view.id&&previous.revision>view.revision)return false;
      const changed=!previous||previous.id!==view.id||previous.revision!==view.revision||previous.current.id!==view.current.id;
      this.state.view=view;
      if(changed){this.stopRecommendations();this.state.recommendations=null;this.state.recommendationError='';}
      return changed;
    }
    async open(id,nodeId='',options={}){
      if(this.state.busy||this.state.pending&&!options.recovery)return false;
      this.viewAbort?.abort();this.viewAbort=typeof AbortController!=='undefined'?new AbortController():null;
      const signal=this.viewAbort?.signal;
      const token=++this.generation;this.stopRecommendations();this.readFailures=0;if(this.state.view?.id!==id){this.state.view=null;this.state.recommendations=null;}this.state.loading=true;this.state.error='';this.notify();
      try{const view=await this.api('editor?id='+encodeURIComponent(id)+(nodeId?'&node_id='+encodeURIComponent(nodeId):''),undefined,{signal});if(token!==this.generation)return false;this.accept(view);const key=view.id+':'+view.current.id+':'+view.revision;if((this.automaticAttempts.get(key)||0)>=3){this.automaticAttempts.delete(key);this.automaticRequested.delete(key);}return true;}
      catch(error){if(token===this.generation)this.state.error=error.message;return false;}
      finally{if(token===this.generation){this.viewAbort=null;this.state.loading=false;this.notify();if(this.state.view&&this.visible)this.loadRecommendations();}}
    }
    savePending(value){if(value){if(!this.storage)throw new Error('No local storage');this.storage.setItem(PENDING_KEY,JSON.stringify(value));}else{try{this.storage?.removeItem(PENDING_KEY);}catch(_){}}this.state.pending=value;}
    async mutate(path,body){
      const s=this.state;if(s.busy||s.loading)return false;
      if(s.pending&&(s.pending.path!==path||JSON.stringify(s.pending.body)!==JSON.stringify(body)))return false;
      try{this.savePending({path,body});}catch(_){s.error='浏览器无法保存这次请求，本次尚未提交。请恢复本地存储后重试。';this.notify();return false;}
      const keepNode=path==='editor_toggle'&&s.view?.id===body.id&&s.view.current.id!==body.node_id?s.view.current.id:null;
      const token=++this.generation;this.stopRecommendations();s.busy=true;s.error='';s.notice='';this.notify();
      try{
        const receipt=await this.api(path,body);
        if(!receipt?.id||!receipt.current?.id)throw new Error('录谱保存结果尚未确认，请重试核对。');
        // A replay receipt can be old. Always read the latest committed draft
        // before allowing another edit, preserving the selected actual path.
        const view=await this.api('editor?id='+encodeURIComponent(receipt.id)+'&node_id='+encodeURIComponent(keepNode||receipt.current.id));
        if(token!==this.generation)return false;
        this.accept(view);this.savePending(null);
        s.notice=path==='editor_publish'?'已发布为训练版本 '+(receipt.published?.version||view.published_version||'')+'。草稿以后仍可继续修改。':path==='editor_record'?'着法已保存。可勾选刚走的这着纳入训练。':path==='editor_toggle'?(body.enabled?'这着已纳入训练。':'这着已移出训练，草稿保留。'):'已保存。';
        this.catalog();return true;
      }catch(error){
        if(error.definitive===true){this.savePending(null);if(body.id){try{const selected=keepNode||body.node_id;this.accept(await this.api('editor?id='+encodeURIComponent(body.id)+(selected?'&node_id='+encodeURIComponent(selected):'')));}catch(_){}}}
        s.error=error.message||'保存结果尚未确认，请重试核对同一次请求。';return false;
      }finally{if(token===this.generation){s.busy=false;this.notify();if(s.view&&this.visible)this.loadRecommendations();}}
    }
    create(title,goal=20){if(this.state.busy||this.state.pending||this.state.loading)return Promise.resolve(false);this.state.view=null;this.state.recommendations=null;return this.mutate('editor_create',{title:title.trim()||'我的开局',goal_plies:goal,request_id:this.newId()});}
    edit(path,fields={}){const v=this.state.view;if(!v||this.state.pending)return Promise.resolve(false);return this.mutate(path,{id:v.id,revision:v.revision,...fields,request_id:this.newId()});}
    update(title,goal){return this.edit('editor_update',{title:title.trim(),goal_plies:goal});}
    record(move,include=false){const current=this.state.view?.current;if(!current?.legal_moves?.includes(move))return Promise.resolve(false);return this.edit('editor_record',{node_id:current.id,move,...(include?{enabled:true}:{})});}
    toggle(move,enabled){return this.edit('editor_toggle',{node_id:this.state.view.current.id,move,enabled:!!enabled});}
    toggleIncoming(enabled){const v=this.state.view,node=v?.nodes?.find(value=>value.id===v.current.id);return node?.parent_id?this.edit('editor_toggle',{node_id:node.parent_id,move:node.move,enabled:!!enabled}):Promise.resolve(false);}
    toggleNode(id,enabled){const node=this.state.view?.nodes?.find(value=>value.id===id);return node?.parent_id?this.edit('editor_toggle',{node_id:node.parent_id,move:node.move,enabled:!!enabled}):Promise.resolve(false);}
    terminal(value){return this.edit('editor_terminal',{node_id:this.state.view.current.id,terminal:!!value});}
    publish(){return this.edit('editor_publish');}
    retry(){const value=this.state.pending;return value?this.mutate(value.path,value.body):Promise.resolve(false);}
    leave(){if(this.state.busy||this.state.pending)return false;++this.generation;this.viewAbort?.abort();this.viewAbort=null;this.stopRecommendations();this.visible=false;this.state.loading=false;return true;}
    setVisible(value){this.visible=!!value;if(!value)this.stopRecommendations();else if(this.state.view)this.loadRecommendations();}
    async loadRecommendations(compute=false,refresh=false,verify=false,automatic=false){
      const context=this.context(),s=this.state;if(!context||!this.visible||s.busy||s.loading||s.pending)return false;
      const key=context.id+':'+context.node_id+':'+context.revision;
      if(automatic){const attempts=this.automaticAttempts.get(key)||0;if(attempts>=3)return false;this.automaticAttempts.set(key,attempts+1);}
      this.stopRecommendations();const token=this.recommendationGeneration;this.abort=typeof AbortController!=='undefined'?new AbortController():null;
      const signal=this.abort?.signal;s.recommendationLoading=!compute;s.recommendationBusy=compute;s.recommendationError='';this.notify('recommendations');
      let accepted=false;
      try{
        const value=await this.api(compute?'editor_recommendations':'editor_recommendations?id='+encodeURIComponent(context.id)+'&node_id='+encodeURIComponent(context.node_id),compute?{...context,refresh:!!refresh,...(verify?{verify:true}:{})}:undefined,{signal});
        if(token!==this.recommendationGeneration||!this.visible||!this.same(context))return false;
        if(value.draft_id!==context.id||value.node_id!==context.node_id||value.revision!==context.revision)return false;
        s.recommendations=value;accepted=true;this.readFailures=0;if(compute)this.automaticRequested.add(key);
        const refining=['queued','running','paused'].includes(value.automatic?.status)&&
          (value.primary?.status!=='verified'||(value.automatic.nodes||0)>(value.primary.budget?.nodes||0));
        const active=['queued','running'].includes(value.status)||value.primary?.status==='verifying';
        const missing=value.primary?.status!=='verified'&&!value.primary?.moves?.length&&value.can_request!==false;
        if(active||refining||missing&&this.automaticRecommendations&&(this.automaticAttempts.get(key)||0)<3)this.timer=this.schedule(()=>{this.timer=null;this.loadRecommendations();},1500);
        if(missing&&!active&&(this.automaticAttempts.get(key)||0)>=3)s.recommendationError='推荐暂未生成，录谱仍可继续；返回此局面时会自动重试。';
        return true;
      }catch(error){if(token===this.recommendationGeneration&&error.name!=='AbortError'){
        s.recommendationError=error.message;if(compute)this.automaticRequested.delete(key);
        const retry=compute?(this.automaticAttempts.get(key)||0)<3:++this.readFailures<=3;
        if(retry&&this.visible&&this.same(context))this.timer=this.schedule(()=>{this.timer=null;this.loadRecommendations();},Math.min(6000,1500*Math.max(1,this.readFailures)));
      }return false;}
      finally{if(token===this.recommendationGeneration){
        s.recommendationLoading=false;s.recommendationBusy=false;this.abort=null;this.notify('recommendations');
        const value=s.recommendations,active=['queued','running'].includes(value?.status)||value?.primary?.status==='verifying',missing=!value?.primary?.moves?.length;
        if(accepted&&!compute&&this.automaticRecommendations&&this.visible&&this.same(context)&&!active&&value?.can_request!==false&&
            (!this.automaticRequested.has(key)||missing)&&(this.automaticAttempts.get(key)||0)<3){
          if(this.automaticAttempts.size>128){const oldest=this.automaticAttempts.keys().next().value;this.automaticAttempts.delete(oldest);this.automaticRequested.delete(oldest);}
          if(value?.primary?.status!=='verified')this.loadRecommendations(true,false,false,true);
        }
      }}
    }
  }
  const api={Controller,pendingValue,scoreText,routes,PENDING_KEY};if(typeof module!=='undefined'&&module.exports)module.exports=api;scope.RepertoireEditor=api;
})(typeof window!=='undefined'?window:globalThis);
