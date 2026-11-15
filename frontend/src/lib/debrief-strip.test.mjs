import assert from 'node:assert/strict';
import test from 'node:test';
import { buildStrip } from './debrief-strip.ts';

test('untimed transcripts never produce a decorative waveform', () => {
  assert.equal(buildStrip([{start_ms:null,end_ms:null,text:'Notes'}],[],10000,40),null);
});
test('word density keeps actual silence and respects boundaries', () => {
  const result=buildStrip([{start_ms:0,end_ms:1000,text:'one two three four'},{start_ms:3000,end_ms:4000,text:'one'}],[],4000,4);
  assert.deepEqual(result.bars,[1,0,0,.5]);
});
test('a turn spanning buckets distributes its words across that interval', () => {
  assert.deepEqual(buildStrip([{start_ms:0,end_ms:4000,text:'one two three four'}],[],4000,4).bars,[1,1,1,1]);
});
test('marks are ordered and out-of-range timestamps are rejected', () => {
  const mark=(at_ms)=>({id:String(at_ms),at_ms,kind:'task',label:'Task',segmentId:'source'});
  const result=buildStrip([{start_ms:0,end_ms:4000,text:'A decision'}],[mark(3000),mark(-1),mark(1000),mark(8000)],4000,4);
  assert.deepEqual(result.marks.map(m=>m.position),[25,75]);
});
test('invalid durations, reversed turns and unbounded bucket counts fail safely', () => {
  assert.equal(buildStrip([],[],NaN,40),null);
  assert.equal(buildStrip([],[],100,10000),null);
  assert.equal(buildStrip([{start_ms:20,end_ms:10,text:'Wrong'}],[],100,4),null);
});
