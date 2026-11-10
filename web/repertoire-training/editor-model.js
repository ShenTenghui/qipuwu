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
    if(value?.type==='mate'&&Number.isInteger(value.mate_distance))return value.mate_distance===0?'�ѱ�����':value.mate_distance>0?'�ɽ�ɱ �� '+value.mate_distance+'��':'����ɱ �� '+Math.abs(value.mate_distance)+'��';
    return '����δȷ��';
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
        result.push({id:node.id,nodes:route,complete:selected&&ended&&!conflict,status:draftPrefix?'δ������� �� �ݸ�ǰ׺':!selected?'��δ�����ŷ�':conflict?'�յ�����������':ended?'����·��':'����¼��'});
      }
      for(const child of next)visit(child,route);
    }
    const root=byId.get(view?.root_id);if(root)visit(root,[]);return result;
  }
  class Controller{
    constructor(api,changed=()=>{},options={}){
      this.api=api;this.changed=changed;this.storage=options.storage||null;
      this.newId=options.newId||(()=>scope.crypto?.randomUUID?.()||'editor-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2));
      this.schedule=options.schedule||((callback,delay)=>setTimeout(callback,delay));this.cancel=options.cancel||clearTimeout;
      this.automaticRecommendations=options.automaticRecommendations!==false;this.automaticRequested=new Set();
      this.visible=true;this.generation=0;this.recommendationGeneration=0;this.timer=null;this.abort=null;
      this.state={drafts:[],view:null,loading:false,busy:false,error:'',notice:'',pending:null,recommendations:null,recommendationLoading:false,recommendationBusy:false,recommendationError:''};
      try{this.state.pending=pendingValue(JSON.parse(this.storage?.getItem(PENDING_KEY)||'null'));}catch(_){}
    }
    notify(){this.changed(this.state);}
    async catalog(){try{const value=await this.api('editor_catalog');this.state.drafts=value.drafts||[];this.notify();return true;}catch(error){this.state.error=error.message;this.notify();return false;}}
    stopRecommendations(){++this.recommendationGeneration;if(this.timer!==null)this.cancel(this.timer);this.timer=null;this.abort?.abort();this.abort=null;this.state.recommendationLoading=false;this.state.recommendationBusy=false;}
    context(){const view=this.state.view;return view?{id:view.id,node_id:view.current.id,revision:view.revision}:null;}
    same(context){const now=this.context();return now&&context&&now.id===context.id&&now.node_id===context.node_id&&now.revision===context.revision;}
    accept(view){
      if(!view||typeof view.id!=='string'||!Number.isInteger(view.revision)||!view.current?.id||!view.current.fen)throw new Error('¼�׻�ִ��δ�������أ������Ժ˶ԡ�');
      const previous=this.state.view;
      if(previous?.id===view.id&&previous.revision>view.revision)return false;
      const changed=!previous||previous.id!==view.id||previous.revision!==view.revision||previous.current.id!==view.current.id;
      this.state.view=view;
      if(changed){this.stopRecommendations();this.state.recommendations=null;this.state.recommendationError='';}
      return changed;
    }
    async open(id,nodeId='',options={}){
      if(this.state.busy||this.state.pending&&!options.recovery)return false;
      const token=++this.generation;this.stopRecommendations();if(this.state.view?.id!==id){this.state.view=null;this.state.recommendations=null;}this.state.loading=true;this.state.error='';this.notify();
      try{const view=await this.api('editor?id='+encodeURIComponent(id)+(nodeId?'&node_id='+encodeURIComponent(nodeId):''));if(token!==this.generation)return false;this.accept(view);return true;}
      catch(error){if(token===this.generation)this.state.error=error.message;return false;}
      finally{if(token===this.generation){this.state.loading=false;this.notify();if(this.state.view&&this.visible)this.loadRecommendations();}}
    }
    savePending(value){if(value){if(!this.storage)throw new Error('No local storage');this.storage.setItem(PENDING_KEY,JSON.stringify(value));}else{try{this.storage?.removeItem(PENDING_KEY);}catch(_){}}this.state.pending=value;}
    async mutate(path,body){
      const s=this.state;if(s.busy||s.loading)return false;
      if(s.pending&&(s.pending.path!==path||JSON.stringify(s.pending.body)!==JSON.stringify(body)))return false;
      try{this.savePending({path,body});}catch(_){s.error='������޷�����������󣬱�����δ�ύ����ָ����ش洢�����ԡ�';this.notify();return false;}
      const keepNode=path==='editor_toggle'&&s.view?.id===body.id&&s.view.current.id!==body.node_id?s.view.current.id:null;
      const token=++this.generation;this.stopRecommendations();s.busy=true;s.error='';s.notice='';this.notify();
      try{
        const receipt=await this.api(path,body);
        if(!receipt?.id||!receipt.current?.id)throw new Error('¼�ױ�������δȷ�ϣ������Ժ˶ԡ�');
        // A replay receipt can be old. Always read the latest committed draft
        // before allowing another edit, preserving the selected actual path.
        const view=await this.api('editor?id='+encodeURIComponent(receipt.id)+'&node_id='+encodeURIComponent(keepNode||receipt.current.id));
        if(token!==this.generation)return false;
        this.accept(view);this.savePending(null);
        s.notice=path==='editor_publish'?'�ѷ���Ϊѵ���汾 '+(receipt.published?.version||view.published_version||'')+'���ݸ��Ժ��Կɼ����޸ġ�':path==='editor_record'?'�ŷ��ѱ��档�ɹ�ѡ���ߵ���������ѵ����':path==='editor_toggle'?(body.enabled?'����������ѵ����':'�������Ƴ�ѵ�����ݸ屣����'):'�ѱ��档';
        this.catalog();return true;
      }catch(error){
        if(error.definitive===true){this.savePending(null);if(body.id){try{const selected=keepNode||body.node_id;this.accept(await this.api('editor?id='+encodeURIComponent(body.id)+(selected?'&node_id='+encodeURIComponent(selected):'')));}catch(_){}}}
        s.error=error.message||'��������δȷ�ϣ������Ժ˶�ͬһ������';return false;
      }finally{if(token===this.generation){s.busy=false;this.notify();if(s.view&&this.visible)this.loadRecommendations();}}
    }
    create(title,goal=20){if(this.state.busy||this.state.pending||this.state.loading)return Promise.resolve(false);this.state.view=null;this.state.recommendations=null;return this.mutate('editor_create',{title:title.trim()||'�ҵĿ���',goal_plies:goal,request_id:this.newId()});}
    edit(path,fields={}){const v=this.state.view;if(!v||this.state.pending)return Promise.resolve(false);return this.mutate(path,{id:v.id,revision:v.revision,...fields,request_id:this.newId()});}
    update(title,goal){return this.edit('editor_update',{title:title.trim(),goal_plies:goal});}
    record(move,include=false){const current=this.state.view?.current;if(!current?.legal_moves?.includes(move))return Promise.resolve(false);return this.edit('editor_record',{node_id:current.id,move,...(include?{enabled:true}:{})});}
    toggle(move,enabled){return this.edit('editor_toggle',{node_id:this.state.view.current.id,move,enabled:!!enabled});}
    toggleIncoming(enabled){const v=this.state.view,node=v?.nodes?.find(value=>value.id===v.current.id);return node?.parent_id?this.edit('editor_toggle',{node_id:node.parent_id,move:node.move,enabled:!!enabled}):Promise.resolve(false);}
    toggleNode(id,enabled){const node=this.state.view?.nodes?.find(value=>value.id===id);return node?.parent_id?this.edit('editor_toggle',{node_id:node.parent_id,move:node.move,enabled:!!enabled}):Promise.resolve(false);}
    terminal(value){return this.edit('editor_terminal',{node_id:this.state.view.current.id,terminal:!!value});}
    publish(){return this.edit('editor_publish');}
    retry(){const value=this.state.pending;return value?this.mutate(value.path,value.body):Promise.resolve(false);}
    leave(){if(this.state.busy||this.state.pending)return false;++this.generation;this.stopRecommendations();this.visible=false;this.state.loading=false;return true;}
    setVisible(value){this.visible=!!value;if(!value)this.stopRecommendations();else if(this.state.view)this.loadRecommendations();}
    async loadRecommendations(compute=false,refresh=false,verify=false){
      const context=this.context(),s=this.state;if(!context||!this.visible||s.busy||s.loading||s.pending)return false;
      this.stopRecommendations();const token=this.recommendationGeneration;this.abort=typeof AbortController!=='undefined'?new AbortController():null;
      const signal=this.abort?.signal;s.recommendationLoading=!compute;s.recommendationBusy=compute;s.recommendationError='';this.notify();
      let accepted=false;
      try{
        const value=await this.api(compute?'editor_recommendations':'editor_recommendations?id='+encodeURIComponent(context.id)+'&node_id='+encodeURIComponent(context.node_id),compute?{...context,refresh:!!refresh,...(verify?{verify:true}:{})}:undefined,{signal});
        if(token!==this.recommendationGeneration||!this.visible||!this.same(context))return false;
        if(value.draft_id!==context.id||value.node_id!==context.node_id||value.revision!==context.revision)return false;
        s.recommendations=value;accepted=true;
        const refining=['queued','running','paused'].includes(value.automatic?.status)&&
          (value.primary?.status!=='verified'||(value.automatic.nodes||0)>(value.primary.budget?.nodes||0));
        if(['queued','running'].includes(value.status)||value.primary?.status==='verifying'||refining)this.timer=this.schedule(()=>{this.timer=null;this.loadRecommendations();},1500);
        return true;
      }catch(error){if(token===this.recommendationGeneration&&error.name!=='AbortError')s.recommendationError=error.message;return false;}
      finally{if(token===this.recommendationGeneration){
        s.recommendationLoading=false;s.recommendationBusy=false;this.abort=null;this.notify();
        const key=context.id+':'+context.node_id+':'+context.revision;
        if(accepted&&!compute&&this.automaticRecommendations&&this.visible&&this.same(context)&&!this.automaticRequested.has(key)){
          this.automaticRequested.add(key);if(this.automaticRequested.size>128)this.automaticRequested.delete(this.automaticRequested.values().next().value);
          if(s.recommendations?.primary?.status!=='verified')this.loadRecommendations(true);
        }
      }}
    }
  }
  const api={Controller,pendingValue,scoreText,routes,PENDING_KEY};if(typeof module!=='undefined'&&module.exports)module.exports=api;scope.RepertoireEditor=api;
})(typeof window!=='undefined'?window:globalThis);
