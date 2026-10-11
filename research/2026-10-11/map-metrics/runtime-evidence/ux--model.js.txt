import {indicatorVisibility} from './indicator-visibility.js';

// Raw observations and the map scale stay separate: normalized values are never statistics.

export function loadedMapMetrics(metrics) {
  // Native ZIP/monitor/tract data alone cannot be shown on the state/county map.
  // Observation totals may be null when the production inventory is uncounted.
  return metrics.filter(metric=>indicatorVisibility[metric.catalogId]===true&&metric.fieldId&&(metric.stateSupported||metric.countySupported));
}

export function collectedMapIndicators(metrics) {
  // The adapter keeps the original indicator ID on its default series; variants use --.
  // Keep variants for existing data cards, but do not turn them into extra picker fields.
  return loadedMapMetrics(metrics).filter(metric=>!metric.id.includes('--'));
}

export async function readAtlasJSON(url,request=fetch) {
  for(let attempt=0;attempt<2;attempt++){
    let response,data;
    try{
      response=await request(url);
      try{data=await response.json();}
      catch{throw new Error('The data service returned an unreadable response. Please retry.');}
    }catch(error){
      if(attempt===0){await new Promise(resolve=>setTimeout(resolve,600));continue;}
      throw new Error(response?'The data service returned an unreadable response. Please retry.':'The data service could not be reached. Please retry.');
    }
    if(response.ok)return data;
    // A tunnel or bounded reader can briefly be busy; only idempotent GETs retry.
    if(attempt===0&&[408,429,502,503,504,530].includes(response.status)){
      await new Promise(resolve=>setTimeout(resolve,600));continue;
    }
    throw new Error(data.error||'The selected data could not be loaded. Please retry.');
  }
}

export function prepareLayer(data,geo) {
  const observations=new Map(),excluded=[...data.excludedGeographies];
  for(const row of data.observations){
    if(row.id!=='US'&&!geo.byId.has(row.id)){excluded.push(row.sourceGeoId);continue;}
    if(!Number.isFinite(row.value)||observations.has(row.id))throw new Error('The series has invalid or ambiguous observations.');
    observations.set(row.id,row);
  }
  const numbers=[...observations].filter(([id])=>id!=='US').map(([,row])=>row.value);
  const min=numbers.length?Math.min(...numbers):null,max=numbers.length?Math.max(...numbers):null;
  const values=new Map([...geo.byId.keys()].map(id=>{
    const v=observations.get(id)?.value;
    return [id,v==null?null:max===min ? .5 :(v-min)/(max-min)];
  }));
  return {...data,status:'ready',observations,values,min,max,excludedGeographies:excluded};
}

export function createDataStore(geo,onChange,request=fetch) {
  const layers=new Map(),pending=new Map();
  function get(metric){
    if(!layers.has(metric.id))layers.set(metric.id,{status:metric.fieldId?'idle':'unavailable',values:new Map(),observations:new Map()});
    return layers.get(metric.id);
  }
  function load(metric){
    if(pending.has(metric.id))return pending.get(metric.id);
    const current=get(metric);
    if(!metric.fieldId||current.status==='ready'||current.status==='error')return Promise.resolve(current);
    layers.set(metric.id,{...current,status:'loading'});
    const promise=(async()=>{
      await Promise.resolve(); // Install request ownership before callbacks, including synchronous fetch failures.
      try{
        const data=await readAtlasJSON('/api/atlas/observations?field='+encodeURIComponent(metric.fieldId),request);
        if(data.fieldId!==metric.fieldId)throw new Error('The server returned a different series.');
        layers.set(metric.id,prepareLayer(data,geo));
      }catch(error){layers.set(metric.id,{status:'error',error:error.message,values:new Map(),observations:new Map()});}
      finally{pending.delete(metric.id);onChange(metric.id);}
      return layers.get(metric.id);
    })();
    pending.set(metric.id,promise);return promise;
  }
  function retry(metric){layers.delete(metric.id);return load(metric);}
  return {get,load,retry};
}

export function missingReason(metric,feature,layer) {
  if(layer.status==='error')return layer.error;
  if(['loading','idle'].includes(layer.status))return 'Loading observations from PostgreSQL…';
  if(!metric.fieldId)return metric.coverageNote;
  if(!feature)return 'No published US observation in this snapshot. Choose a state or county; no average is substituted.';
  if(feature.id.length===5&&!metric.countySupported)return 'This is a state-level series. No county value is inferred from the state value.';
  if(feature.id.length===2&&!metric.stateSupported)return 'This series contains county observations. Choose a county; no state value is inferred.';
  return `No observation for this FIPS in the ${formatPeriod(layer.period)} snapshot. The map uses Census 2017 boundaries; unmatched or missing places remain empty.`;
}
export function formatValue(value,unit='') {
  if(value==null)return '—';
  const number=new Intl.NumberFormat('en-US',{maximumFractionDigits:unit==='per 1,000 people'?6:2}).format(value);
  return unit==='%'?number+'%':number;
}
export function formatPeriod(period='') {
  const match=period.match(/^(\d{4})-M(\d{2})$/);
  return match?new Intl.DateTimeFormat('en-US',{month:'short',year:'numeric',timeZone:'UTC'}).format(new Date(Date.UTC(+match[1],+match[2]-1,1))):period;
}
export function comparable(a,b,placeA,placeB) {
  return a.status==='ready'&&b.status==='ready'&&a.fieldId===b.fieldId&&a.period===b.period&&
    a.sourceRelease===b.sourceRelease&&a.unit===b.unit&&Boolean(placeA)&&Boolean(placeB)&&placeA.id.length===placeB.id.length;
}
