(function () {
  const form = document.getElementById("analyze-form");
  if (!form) return;

  const COLORS = {LOW:"#42D67A",MEDIUM:"#D7B43A",HIGH:"#F0802C",CRITICAL:"#FF4D57"};
  const LABELS = {methane:"Methane",co:"CO",temperature:"Temperature",humidity:"Humidity",dust:"Dust",vibration:"Vibration",noise:"Noise",worker_count:"Worker count",worker_hazard_distance:"Worker proximity",ppe_violations:"PPE violations",equipment_temperature:"Equipment temperature",equipment_overheating:"Overheating",equipment_health:"Equipment health",slope_stability:"Slope stability",wind_speed:"Wind speed",rainfall:"Rainfall",visibility:"Visibility"};
  const params = new URLSearchParams(window.location.search);
  const zoneParam=params.get("zone"), zoneSelect=form.querySelector("select[name='zone']");
  if(zoneParam && zoneSelect && [...zoneSelect.options].some(o=>o.value===zoneParam)) zoneSelect.value=zoneParam;
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  function setProgressStage(index){document.querySelectorAll(".progress-stage").forEach((stage,i)=>{stage.classList.toggle("stage-active",i===index);stage.classList.toggle("stage-complete",i<index);});}

  form.addEventListener("submit",async e=>{
    e.preventDefault();
    const fd=new FormData(form);
    const payload={};
    ["methane","co","temperature","humidity","dust","vibration","noise","worker_count","worker_hazard_distance","ppe_violations","equipment_temperature","equipment_health","slope_stability","wind_speed","rainfall","visibility"].forEach(k=>payload[k]=Number(fd.get(k)||0));
    payload.equipment_overheating=Number(fd.get("equipment_overheating")||0);
    payload.ventilation_status=fd.get("ventilation_status"); payload.zone=fd.get("zone");
    const button=document.getElementById("analyze-submit"), buttonText=button?.querySelector("span:nth-child(2)");
    if(button){button.disabled=true;button.classList.add("is-loading");if(buttonText)buttonText.textContent="Running model...";}
    document.getElementById("result-placeholder")?.classList.add("hidden");document.getElementById("result-panel")?.classList.add("hidden");document.getElementById("analysis-progress")?.classList.remove("hidden");
    try{
      setProgressStage(0);await sleep(240);setProgressStage(1);await sleep(250);
      const response=await fetch("/api/analyze",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
      const result=await response.json();if(!response.ok)throw new Error(result.error||"Analysis failed.");
      await sleep(220);setProgressStage(2);await sleep(180);setProgressStage(3);await sleep(180);renderResult(result);
      window.showToast?.("AI ANALYSIS COMPLETE",`${result.zone} classified as ${result.risk}`,['CRITICAL','HIGH'].includes(result.risk)?"error":"success");
    }catch(error){console.error(error);document.getElementById("analysis-progress")?.classList.add("hidden");document.getElementById("result-placeholder")?.classList.remove("hidden");window.showToast?.("ANALYSIS FAILED",error.message,"error");}
    finally{if(button){button.disabled=false;button.classList.remove("is-loading");if(buttonText)buttonText.textContent="Run AI Risk Analysis";}}
  });

  function renderResult(result){
    document.getElementById("analysis-progress")?.classList.add("hidden");const panel=document.getElementById("result-panel");panel?.classList.remove("hidden","result-reveal");void panel?.offsetWidth;panel?.classList.add("result-reveal");
    const risk=result.risk||"LOW",color=COLORS[risk]||COLORS.LOW,hero=document.getElementById("result-hero"),badge=document.getElementById("result-badge"),bar=document.getElementById("result-score-bar"),label=document.getElementById("result-score-label");
    badge.textContent=risk;badge.style.color=color;hero.style.setProperty("--risk-color",color);label.textContent="0 / 100";bar.style.width="0%";bar.style.background=`linear-gradient(90deg,${color}AA,${color})`;
    document.getElementById("result-rule-count").textContent=`${Number(result.confidence||0).toFixed(1)}%`;
    document.getElementById("result-summary").textContent=`${Number(result.probability*100||0).toFixed(1)}% probability of ${risk} · ${result.model_type}.`;
    requestAnimationFrame(()=>setTimeout(()=>{animateCount(label,Number(result.risk_score||0),color);bar.style.width=`${Number(result.risk_score||0)}%`;},80));
    const dist=Object.entries(result.distribution||{}),rulesContainer=document.getElementById("result-rules");rulesContainer.innerHTML=dist.map(([k,v])=>`<div class="rule-card" style="--rule-color:${COLORS[k]||COLORS.LOW}"><div class="rule-card-top"><div class="rule-id">${k}</div><span class="badge" data-severity="${k}">${k}</span></div><div class="rule-card-explanation"><div class="prob-track"><i style="width:${Number(v)*100}%"></i></div><b>${(Number(v)*100).toFixed(1)}%</b></div></div>`).join("");
    const actions=document.getElementById("result-actions");actions.innerHTML=(result.top_factors||[]).map((f,i)=>`<li><span class="action-index">0${i+1}</span><span><b>${escapeHtml(LABELS[f.feature]||f.feature)}</b> <small>learned impact ${Number(f.impact||0).toFixed(1)}%</small></span></li>`).join("") || '<li><span>No strong signals returned.</span></li>';
    document.getElementById("result-zone-meta").textContent=`ZONE // ${String(result.zone||"—").toUpperCase()}`;document.getElementById("result-time-meta").textContent=`TIME // ${result.analyzed_at||"—"}`;document.getElementById("result-alert-meta").textContent=result.alert_id?`ALERT // ${result.alert_id}`:"ALERT // NOT GENERATED";
    window.scrollTo({top:0,behavior:"smooth"});
  }
  function animateCount(element,target,color){const start=performance.now(),duration=650;function frame(now){const p=Math.min(1,(now-start)/duration),e=1-Math.pow(1-p,3);element.textContent=`${Math.round(target*e)} / 100`;element.style.color=color;if(p<1)requestAnimationFrame(frame);}requestAnimationFrame(frame);}
  function escapeHtml(value){const el=document.createElement("div");el.textContent=value==null?"":String(value);return el.innerHTML;}
})();
