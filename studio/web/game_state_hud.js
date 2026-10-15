/* P1 read-only stats and explicit profile actions. Never accepts model effects. */
(function(root){
 'use strict';
 class GameStateHUD {
  constructor({request,render,beforeSwitch=async()=>{},onSwitch=async()=>{}}){
   Object.assign(this,{request,render,beforeSwitch,onSwitch});this.generation=0;this.session=null;
  }
  async refresh(){
   if(this.selecting)return false;
   const generation=++this.generation;
   try{
    const [state,profiles]=await Promise.all([this.request('/api/game/state'),this.request('/api/game/profiles')]);
    if(generation!==this.generation)return false;
    if(state.profile_id!==profiles.selected)throw Error('存档正在切换，请刷新状态');
    const session=profiles.selected+':'+profiles.generation;
    if(this.session!==null&&this.session!==session){
     await this.beforeSwitch();if(generation!==this.generation)return false;
     await this.onSwitch();if(generation!==this.generation)return false;
    }
    this.session=session;
    this.render({state,profiles:profiles.profiles});return true;
   }catch(error){if(generation===this.generation)this.render({error:error.message});return false;}
  }
  async select(id){
   if(this.selecting)throw Error('存档切换中，请稍候');
   this.selecting=true;
   const generation=++this.generation;
   try{
    await this.beforeSwitch();if(generation!==this.generation)return false;
    await this.request('/api/game/profile',{action:'select',id});
    if(generation!==this.generation)return false;
    this.session=null;await this.onSwitch();
   }finally{this.selecting=false;}
   return this.refresh();
  }
 }
 if(typeof module!=='undefined'&&module.exports)module.exports=GameStateHUD;
 else root.GameStateHUD=GameStateHUD;
})(typeof window==='undefined'?globalThis:window);
