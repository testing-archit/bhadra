import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function setup() {
  const nodes = [];
  const make = type => {
    const data = {};
    const node = {id: String(nodes.length+1), type, x:0,y:0,locked:false,text:{characters:''},
      getPluginData:key=>data[key]||'',setPluginData:(key,value)=>{data[key]=value},resize(){},remove(){nodes.splice(nodes.indexOf(node),1)}};
    nodes.push(node); return node;
  };
  const figma = {showUI(){},on(){},ui:{},currentPage:{id:'page',on(){},findAll:fn=>nodes.filter(fn)},
    createShapeWithText:()=>make('SHAPE_WITH_TEXT'),createConnector:()=>make('CONNECTOR'),commitUndo(){}};
  const context = vm.createContext({figma,__html__:'',setInterval(){},console});
  vm.runInContext(fs.readFileSync(new URL('./code.js',import.meta.url),'utf8'),context);
  vm.runInContext('connection={connection_id:"meeting-one"}',context);
  function apply(baseline,snapshot) {
    context.delivery={baseline,snapshot};
    return vm.runInContext('applySnapshot(delivery)',context);
  }
  return {nodes,apply,make};
}
const empty={nodes:[],edges:[]};
const point=(id,title,x=80)=>({id,title,text:'',kind:'idea',x,y:100,locked:false,origin:'ai'});

test('native shapes/connectors persist and replay does not duplicate them',()=>{
  const s=setup();
  const diagram={nodes:[point('signup','Signup'),point('payment','Payment',450)],edges:[{id:'flow',source:'signup',target:'payment'}]};
  assert.equal(s.apply(empty,diagram),'applied');
  assert.equal(s.nodes.length,3);
  assert.equal(s.apply(empty,diagram),'applied');
  assert.equal(s.nodes.length,3);
  assert.equal(s.nodes.find(n=>n.type==='CONNECTOR').connectorStart.endpointNodeId,s.nodes[0].id);
});
test('concurrent human edits cause a conflict before another point is changed',()=>{
  const s=setup();
  const before={nodes:[point('signup','Signup'),point('payment','Payment',450)],edges:[]};
  s.apply(empty,before);
  s.nodes[1].text.characters='Payment by bank transfer';
  const after={nodes:[point('signup','Create account'),point('payment','Pay now',450)],edges:[]};
  assert.equal(s.apply(before,after),'conflict');
  assert.equal(s.nodes[0].text.characters,'Signup');
  assert.equal(s.nodes[1].text.characters,'Payment by bank transfer');
});
test('unmanaged FigJam objects are preserved and unchanged points keep human edits',()=>{
  const s=setup();
  const human=s.make('SHAPE_WITH_TEXT');human.text.characters='Team brainstorm';
  const before={nodes:[point('signup','Signup')],edges:[]};
  s.apply(empty,before);
  s.nodes[1].x=120;
  const after={nodes:[point('signup','Signup'),point('payment','Payment',450)],edges:[]};
  assert.equal(s.apply(before,after),'applied');
  assert.equal(s.nodes[1].x,120);
  assert.ok(s.nodes.includes(human));
});
