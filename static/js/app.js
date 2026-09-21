(function () {
  const clock = document.getElementById("clock");
  const popup = document.getElementById("zone-popup");
  const closePopup = document.getElementById("close-zone-popup");
  const mobileToggle = document.getElementById("mobile-nav-toggle");
  const sidebar = document.getElementById("sidebar");
  const zoneObservations = window.zoneObservations || {};
  const zoneStatuses = window.zoneStatuses || {};

  const COLORS = { LOW: "#42D67A", MEDIUM: "#D7B43A", HIGH: "#F0802C", CRITICAL: "#FF4D57" };
  const ZONE_CODES = { "North Pit":"Z-01", "Conveyor Zone":"Z-02", "Processing Area":"Z-03", "South Pit":"Z-04", "Storage Area":"Z-05" };

  function updateClock() {
    if (!clock) return;
    clock.textContent = new Date().toLocaleTimeString("en-IN", { hour12:false, hour:"2-digit", minute:"2-digit", second:"2-digit" });
  }
  updateClock(); window.setInterval(updateClock, 1000);

  function toast(title, message, type = "info") {
    const stack = document.getElementById("toast-stack"); if (!stack) return;
    const item = document.createElement("div"); item.className = `toast toast-${type}`;
    item.innerHTML = `<div class="toast-mark">${type === "error" ? "!" : "✓"}</div><div><b>${escapeHtml(title)}</b><span>${escapeHtml(message)}</span></div><button type="button" aria-label="Dismiss">×</button>`;
    item.querySelector("button").addEventListener("click", () => item.remove()); stack.appendChild(item); window.setTimeout(() => item.remove(), 4200);
  }
  window.showToast = toast;

  function openZonePopup(zoneName, status) {
    if (!popup) return;
    const observation = zoneObservations[zoneName] || {}; const color = COLORS[status] || COLORS.LOW;
    document.getElementById("popup-zone-name").textContent = zoneName;
    document.getElementById("popup-zone-code").textContent = ZONE_CODES[zoneName] || "Z-00";
    document.getElementById("popup-zone-status").textContent = status;
    document.getElementById("popup-zone-status").style.color = color;
    const statusNote = document.getElementById("popup-zone-status-note"); statusNote.textContent = status === "LOW" ? "WITHIN DEMO RANGE" : `${status} CONDITION DETECTED`; statusNote.style.color = color;
    const dot = document.getElementById("popup-status-dot"); dot.style.backgroundColor=color; dot.style.color=color; dot.style.boxShadow=`0 0 12px ${color}`;
    document.getElementById("popup-methane").textContent = observation.methane !== undefined ? `${observation.methane}%` : "—";
    document.getElementById("popup-dust").textContent = observation.dust !== undefined ? `${observation.dust}` : "—";
    document.getElementById("popup-temperature").textContent = observation.temperature !== undefined ? `${observation.temperature}°C` : "—";
    document.getElementById("popup-vibration").textContent = observation.vibration !== undefined ? `${observation.vibration}` : "—";
    document.getElementById("popup-ventilation").textContent = (observation.ventilation_status || "good").toUpperCase();
    document.getElementById("popup-time").textContent = observation.last_analysis || "DEMO STATE";
    const analyzeLink = document.getElementById("popup-analyze-link"); if (analyzeLink) analyzeLink.href = `/analyze?zone=${encodeURIComponent(zoneName)}`;
    popup.classList.remove("hidden"); requestAnimationFrame(() => popup.classList.add("is-open"));
    const interactionStatus = document.getElementById("map-interaction-status"); if (interactionStatus) interactionStatus.textContent = `${ZONE_CODES[zoneName] || "Z-00"} · ${status}`;
  }
  window.openZonePopup = openZonePopup;

  function closeZonePopup() {
    if (!popup) return; popup.classList.remove("is-open"); window.setTimeout(() => popup.classList.add("hidden"), 190);
    const interactionStatus = document.getElementById("map-interaction-status"); if (interactionStatus) interactionStatus.textContent = "SELECT A ZONE";
  }

  closePopup?.addEventListener("click", closeZonePopup);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeZonePopup();
    if (event.key === "/" && !["INPUT","TEXTAREA"].includes(document.activeElement?.tagName)) document.querySelector(".nav-link[href='/analyze']")?.focus();
  });
  mobileToggle?.addEventListener("click", () => sidebar?.classList.toggle("sidebar-open"));
  document.querySelectorAll(".nav-link").forEach((link) => link.addEventListener("click", () => sidebar?.classList.remove("sidebar-open")));

  document.querySelectorAll(".audit-event").forEach((eventButton) => eventButton.addEventListener("click", () => {
    const expanded = eventButton.getAttribute("aria-expanded") === "true"; eventButton.setAttribute("aria-expanded", String(!expanded));
  }));
  document.querySelectorAll(".alert-summary").forEach((summary) => summary.addEventListener("click", () => {
    const expanded = summary.getAttribute("aria-expanded") === "true"; summary.setAttribute("aria-expanded", String(!expanded)); summary.closest(".alert-card")?.classList.toggle("alert-expanded", !expanded);
  }));

  document.querySelectorAll("[data-jump-zone]").forEach((button) => button.addEventListener("click", () => {
    const zone = button.dataset.jumpZone;
    if (window.focusMineZone) { window.focusMineZone(zone); document.getElementById("mine-map")?.scrollIntoView({behavior:"smooth", block:"center"}); }
  }));

  function escapeHtml(value) { const element = document.createElement("div"); element.textContent = value == null ? "" : String(value); return element.innerHTML; }
})();

/*
 * Real 3D holographic open-cast mine visualization.
 * Visual layer only: Flask remains the source of truth for risk and zone state.
 */
(function initHolographicMineMap() {
  const viewport = document.getElementById("mine-3d-viewport");
  const canvas = document.getElementById("mine-3d-canvas");
  if (!viewport || !canvas || !window.zoneStatuses) return;

  const loading = document.getElementById("mine-3d-loading");
  const labelsEl = document.getElementById("mine-zone-labels");
  const zoneStatuses = window.zoneStatuses || {};
  const COLORS = { LOW:0x43e58b, MEDIUM:0xf2c94c, HIGH:0xff5e5e, CRITICAL:0xff3f68 };
  const ZONE_CODES = { "North Pit":"Z-01", "Conveyor Zone":"Z-02", "Processing Area":"Z-03", "South Pit":"Z-04", "Storage Area":"Z-05" };

  import("https://cdn.jsdelivr.net/npm/three@0.176.0/build/three.module.js")
    .then(THREE => buildScene(THREE))
    .catch(error => {
      console.error("3D mine view failed:", error);
      if (loading) loading.innerHTML = "<span>3D VIEW UNAVAILABLE · CHECK INTERNET CONNECTION</span>";
    });

  function buildScene(THREE) {
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x06111a);
    scene.fog = new THREE.Fog(0x06111a, 45, 120);

    const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 180);
    let targetZoom = 1.0;

    const renderer = new THREE.WebGLRenderer({ canvas, antialias:true, alpha:false, powerPreference:"high-performance" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.18;

    scene.add(new THREE.HemisphereLight(0xa9e8ff, 0x081016, 1.35));
    const key = new THREE.DirectionalLight(0xd7faff, 2.3);
    key.position.set(-18, 34, 20);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    scene.add(key);
    const cyanLight = new THREE.PointLight(0x32ddcf, 32, 55, 2);
    cyanLight.position.set(5, 9, 1);
    scene.add(cyanLight);
    const blueLight = new THREE.PointLight(0x2e8cff, 18, 50, 2);
    blueLight.position.set(-18, 6, -10);
    scene.add(blueLight);

    const world = new THREE.Group();
    world.rotation.order = "YXZ";
    scene.add(world);

    let yaw = 0.48;
    let pitch = -0.26;
    let dragging = false;
    let lastPointer = { x:0, y:0 };

    const MAT = {
      terrain: new THREE.MeshStandardMaterial({color:0x16232a, roughness:.96, metalness:.05}),
      rock: new THREE.MeshStandardMaterial({color:0x1b2b31, emissive:0x0b1d21, emissiveIntensity:.28, roughness:.92}),
      rockDeep: new THREE.MeshStandardMaterial({color:0x101b20, emissive:0x071316, emissiveIntensity:.16, roughness:.98}),
      road: new THREE.MeshStandardMaterial({color:0x283940, emissive:0x09191d, emissiveIntensity:.18, roughness:.8}),
      roadEdge: new THREE.MeshBasicMaterial({color:0x5ee8dc, transparent:true, opacity:.34}),
      holo: new THREE.MeshPhysicalMaterial({color:0x68e9df, emissive:0x237873, emissiveIntensity:.45, transparent:true, opacity:.72, roughness:.18, metalness:.28}),
      glass: new THREE.MeshPhysicalMaterial({color:0x54dfe5, emissive:0x175f66, emissiveIntensity:.45, transparent:true, opacity:.34, roughness:.12, metalness:.22, transmission:.08}),
      blueGlass: new THREE.MeshPhysicalMaterial({color:0x4ba4ff, emissive:0x1754a0, emissiveIntensity:.62, transparent:true, opacity:.35, roughness:.1, metalness:.22}),
      gold: new THREE.MeshStandardMaterial({color:0xf0b63c, emissive:0x6b3504, emissiveIntensity:.35, metalness:.38, roughness:.46}),
      dark: new THREE.MeshStandardMaterial({color:0x102027, emissive:0x0a252c, emissiveIntensity:.18, roughness:.7, metalness:.32})
    };

    function edgeBox(w,h,d,color=0x64e7df,opacity=.42){
      const geo = new THREE.EdgesGeometry(new THREE.BoxGeometry(w+.03,h+.03,d+.03));
      return new THREE.LineSegments(geo,new THREE.LineBasicMaterial({color,transparent:true,opacity}));
    }

    // Site base: restrained, not a giant glowing platform.
    const site = new THREE.Mesh(new THREE.PlaneGeometry(58,48), MAT.terrain);
    site.rotation.x = -Math.PI/2;
    site.position.y = -0.18;
    site.receiveShadow = true;
    world.add(site);

    const grid = new THREE.GridHelper(58, 29, 0x173f4a, 0x0c242c);
    grid.position.y = -0.14;
    grid.material.transparent = true;
    grid.material.opacity = .17;
    world.add(grid);

    // Mine perimeter glow — very subtle.
    const perimeter = new THREE.LineLoop(
      new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(-28,0,-23), new THREE.Vector3(28,0,-23),
        new THREE.Vector3(28,0,23), new THREE.Vector3(-28,0,23)
      ]),
      new THREE.LineBasicMaterial({color:0x1a6772,transparent:true,opacity:.28})
    );
    world.add(perimeter);

    // Concentric terraced open-cast benches. Each level is a real 3D ring made from four solids.
    function addBench(outerW, outerD, innerW, innerD, y, height, tint){
      const g = new THREE.Group();
      const mat = new THREE.MeshStandardMaterial({color:tint, emissive:0x0e262b, emissiveIntensity:.2, roughness:.98});
      const sideX = (outerW-innerW)/2;
      const sideZ = (outerD-innerD)/2;
      const pieces = [
        [outerW, height, sideZ, 0, y, -(outerD-sideZ)/2],
        [outerW, height, sideZ, 0, y, +(outerD-sideZ)/2],
        [sideX, height, innerD, -(outerW-sideX)/2, y, 0],
        [sideX, height, innerD, +(outerW-sideX)/2, y, 0]
      ];
      pieces.forEach(([w,h,d,x,py,z])=>{
        const m = new THREE.Mesh(new THREE.BoxGeometry(w,h,d), mat);
        m.position.set(x,py,z); m.castShadow=true; m.receiveShadow=true; g.add(m);
        const e = edgeBox(w,h,d,tint===0x24363a?0x62dcd4:0x4db8ff,.30);
        e.position.copy(m.position); g.add(e);
      });
      world.add(g);
      return g;
    }

    addBench(40,33,31,24,0.10,.75,0x24363a);
    addBench(31.5,24.5,24.0,17.8,-0.85,.78,0x1d2e33);
    addBench(24.5,18.2,17.2,12.0,-1.80,.78,0x17282d);
    addBench(17.6,12.4,10.6,6.4,-2.74,.78,0x122126);

    const pitFloor = new THREE.Mesh(new THREE.BoxGeometry(10.2,.45,6.0), MAT.rockDeep);
    pitFloor.position.set(0,-3.25,1.2);
    pitFloor.receiveShadow=true;
    world.add(pitFloor);
    const pitFloorEdge = edgeBox(10.2,.45,6.0,0x3dc7c0,.46); pitFloorEdge.position.copy(pitFloor.position); world.add(pitFloorEdge);

    // Terraced slope highlights, keeping the geology readable.
    for(let i=0;i<18;i++){
      const a = (i/18)*Math.PI*2;
      const r = 9.0 + (i%3)*1.5;
      const line = new THREE.Mesh(new THREE.BoxGeometry(3.5,.07,.08), new THREE.MeshBasicMaterial({color:0x3a706f,transparent:true,opacity:.42}));
      line.position.set(Math.cos(a)*r,-2.35,1.2+Math.sin(a)*r*.52);
      line.rotation.y = -a;
      world.add(line);
    }

    // Haul roads: dark ribbons with thin holographic edge lights.
    function addRoad(points, width=1.0){
      const curve = new THREE.CatmullRomCurve3(points.map(([x,y,z])=>new THREE.Vector3(x,y,z)));
      const road = new THREE.Mesh(new THREE.TubeGeometry(curve,80,width,4,false), MAT.road);
      road.castShadow=true; road.receiveShadow=true; world.add(road);
      const edgeGeometry = new THREE.BufferGeometry().setFromPoints(curve.getPoints(90));
      const edge = new THREE.Line(edgeGeometry, new THREE.LineBasicMaterial({color:0x4adfd3,transparent:true,opacity:.24}));
      world.add(edge);
    }
    addRoad([[-22,.05,-15],[-15,.02,-11],[-11,-.30,-8],[-7,-.95,-6],[-3,-1.85,-4],[0,-2.5,-2.7]],1.05);
    addRoad([[23,.05,11],[16,.02,9],[12,-.45,7],[8,-1.25,5],[4,-2.2,3]],.94);
    addRoad([[-20,.05,10],[-13,.02,9],[-9,.02,7],[-7,-.4,4]],.88);

    // Perimeter trees — dark, low-profile so they frame the mine instead of hiding it.
    function addTree(x,z,s=1){
      const g=new THREE.Group(); g.position.set(x,0,z);
      const trunk=new THREE.Mesh(new THREE.CylinderGeometry(.08*s,.11*s,.42*s,7),MAT.dark); trunk.position.y=.22*s; g.add(trunk);
      for(let i=0;i<3;i++){
        const c=new THREE.Mesh(new THREE.ConeGeometry((.35-.045*i)*s,(.72-.05*i)*s,7),new THREE.MeshStandardMaterial({color:0x13362f,emissive:0x08231f,emissiveIntensity:.18,roughness:.95}));
        c.position.y=(.62+i*.24)*s; g.add(c);
      }
      world.add(g);
    }
    for(let x=-24;x<=24;x+=2.4){ addTree(x,-20.4,.65); if(x%4===0) addTree(x,19.5,.6); }
    for(let z=-16;z<=17;z+=2.7){ addTree(-24.5,z,.6); addTree(23.7,z,.55); }

    const zoneData = {
      "North Pit": {p:[-7.5,0.55,-12.2],r:5.0,label:"North Zone"},
      "Conveyor Zone": {p:[-13.0,0.35,4.6],r:4.4,label:"West Zone"},
      "Processing Area": {p:[11.8,0.55,6.4],r:4.7,label:"Processing Plant"},
      "South Pit": {p:[1.0,-2.05,-0.6],r:5.1,label:"Central Zone"},
      "Storage Area": {p:[13.0,0.75,-7.0],r:4.3,label:"East Zone"}
    };
    const zoneGroups={};

    function makeZone(name,data){
      const status = zoneStatuses[name] || "LOW";
      const c = COLORS[status] || COLORS.LOW;
      const g = new THREE.Group();
      g.position.set(...data.p);
      g.userData={type:"zone",zone:name,home:data.p.slice(),baseY:data.p[1],label:data.label};
      world.add(g); zoneGroups[name]=g;

      const ring = new THREE.Mesh(new THREE.RingGeometry(data.r-.14,data.r+.10,96),new THREE.MeshBasicMaterial({color:c,transparent:true,opacity:.70,side:THREE.DoubleSide}));
      ring.rotation.x=-Math.PI/2; ring.position.y=.08;
      ring.userData={hoverTarget:g,type:"zone",zone:name}; g.add(ring);
      const halo = new THREE.Mesh(new THREE.RingGeometry(data.r-.78,data.r+.78,96),new THREE.MeshBasicMaterial({color:c,transparent:true,opacity:.07,side:THREE.DoubleSide}));
      halo.rotation.x=-Math.PI/2; halo.position.y=.04; halo.userData={hoverTarget:g,type:"zone",zone:name}; g.add(halo);
      const pad = new THREE.Mesh(new THREE.CylinderGeometry(data.r*.72,data.r*.72,.10,64),new THREE.MeshStandardMaterial({color:c,emissive:c,emissiveIntensity:.13,transparent:true,opacity:.075,roughness:.55,metalness:.08}));
      pad.position.y=-.02; pad.userData={hoverTarget:g,type:"zone",zone:name}; g.add(pad);
      if(name==="South Pit") pad.position.y=-.02;
      g.traverse(o=>{if(o.userData){o.userData.hoverTarget=g;o.userData.type="zone";o.userData.zone=name;}});
    }
    Object.entries(zoneData).forEach(([n,d])=>makeZone(n,d));

    function addBuilding(zoneName,pos,type,label,scale=1){
      const g=new THREE.Group();
      g.position.set(...pos);
      g.scale.setScalar(scale);
      g.userData={type:"building",zone:zoneName,label,baseY:g.position.y,baseRot:0};
      const fill = type==="plant" ? MAT.blueGlass : MAT.holo;
      const darkFill = type==="plant" ? new THREE.MeshStandardMaterial({color:0x16313a,emissive:0x0b3038,emissiveIntensity:.28,roughness:.52,metalness:.25}) : MAT.dark;

      function part(mesh, hoverTarget=true){
        mesh.castShadow=true; mesh.receiveShadow=true; g.add(mesh);
        if(hoverTarget){ const e=edgeBox(mesh.geometry.parameters.width||1,mesh.geometry.parameters.height||1,mesh.geometry.parameters.depth||1,0x7ffbf1,.38); e.position.copy(mesh.position); g.add(e); }
      }

      if(type==="plant"){
        const main=new THREE.Mesh(new THREE.BoxGeometry(4.7,2.2,3.2),darkFill); part(main);
        const roof=new THREE.Mesh(new THREE.BoxGeometry(4.9,.16,3.4),fill); roof.position.y=1.15; part(roof,false);
        [[-1.6,1.7,-.8,.75,3.3,.75],[.0,1.8,.7,.82,3.8,.82],[1.55,1.4,-.55,.72,2.6,.72]].forEach(([x,y,z,w,h,d])=>{const t=new THREE.Mesh(new THREE.BoxGeometry(w,h,d),fill);t.position.set(x,y,z);part(t,false);});
        for(let i=0;i<3;i++){const pipe=new THREE.Mesh(new THREE.CylinderGeometry(.09,.09,2.8,10),new THREE.MeshBasicMaterial({color:0x91fff4,transparent:true,opacity:.58}));pipe.position.set(-1.2+i*1.2,1.7,-1.72);part(pipe,false);}
      } else if(type==="tower"){
        const body=new THREE.Mesh(new THREE.BoxGeometry(1.0,3.9,1.0),fill); part(body);
        for(let i=0;i<3;i++){const deck=new THREE.Mesh(new THREE.BoxGeometry(1.45,.10,1.45),new THREE.MeshBasicMaterial({color:0x8bfff5,transparent:true,opacity:.55}));deck.position.y=-1.2+i*1.1;part(deck,false);}
        const tip=new THREE.Mesh(new THREE.CylinderGeometry(.12,.12,1.3,10),new THREE.MeshBasicMaterial({color:0x9dfff6}));tip.position.y=2.7;part(tip,false);
      } else if(type==="fuel"){
        const office=new THREE.Mesh(new THREE.BoxGeometry(2.0,1.15,1.4),darkFill); part(office);
        for(let i=0;i<2;i++){const tank=new THREE.Mesh(new THREE.CylinderGeometry(.58,.58,1.8,20),fill);tank.rotation.z=Math.PI/2;tank.position.set((i-.5)*2.0,.65,.5);part(tank,false);}
        const canopy=new THREE.Mesh(new THREE.BoxGeometry(2.8,.12,2.0),fill);canopy.position.y=1.45;part(canopy,false);
      } else if(type==="storage"){
        const body=new THREE.Mesh(new THREE.BoxGeometry(2.8,1.5,2.0),darkFill);part(body);
        const roof=new THREE.Mesh(new THREE.BoxGeometry(3.0,.18,2.2),fill);roof.position.y=.84;part(roof,false);
        for(let i=0;i<2;i++){const s=new THREE.Mesh(new THREE.CylinderGeometry(.48,.48,2.4,24),fill);s.position.set((i-.5)*1.4,1.2,1.35);part(s,false);}
      } else {
        const body=new THREE.Mesh(new THREE.BoxGeometry(2.5,1.5,1.9),darkFill);part(body);
        const roof=new THREE.Mesh(new THREE.ConeGeometry(1.7,.75,4),fill);roof.position.y=1.1;roof.rotation.y=Math.PI/4;part(roof,false);
        const glass=new THREE.Mesh(new THREE.BoxGeometry(1.6,.48,.08),new THREE.MeshBasicMaterial({color:0x8bfff7,transparent:true,opacity:.60}));glass.position.set(0,.15,1.0);part(glass,false);
      }

      g.traverse(o=>{ if(o.userData){ o.userData.hoverTarget=g; o.userData.type="building"; o.userData.zone=zoneName; o.userData.label=label; }});
      world.add(g);
      return g;
    }

    // Facilities arranged like an actual surface mine around the pit.
    addBuilding("North Pit",[-10,0.35,-8.6],"building","WORKSHOP",1.05);
    addBuilding("North Pit",[-5.0,0.35,-10.0],"tower","VENTILATION TOWER",.95);
    addBuilding("Conveyor Zone",[-13.2,0.25,4.9],"tower","TRANSFER TOWER",.95);
    addBuilding("Conveyor Zone",[-16.0,0.20,2.7],"storage","CONVEYOR MOTOR",.85);
    addBuilding("Processing Area",[10.8,0.6,5.8],"plant","PROCESSING PLANT",1.0);
    addBuilding("Processing Area",[14.8,0.6,7.8],"tower","PROCESS STACK",.9);
    addBuilding("South Pit",[6.7,0.20,-7.2],"building","ADMINISTRATION",.85);
    addBuilding("Storage Area",[13.2,0.55,-5.0],"storage","STORAGE FACILITY",.9);
    addBuilding("Storage Area",[16.0,0.45,-7.7],"fuel","FUEL STATION",.78);

    function addExcavator(pos,sc=.9,rot=-.2){
      const g=new THREE.Group(); g.position.set(...pos); g.rotation.y=rot; g.userData={type:"equipment"};
      const base=new THREE.Mesh(new THREE.BoxGeometry(1.2*sc,.35*sc,.78*sc),MAT.gold);base.castShadow=true;g.add(base);
      const cab=new THREE.Mesh(new THREE.BoxGeometry(.48*sc,.45*sc,.52*sc),MAT.blueGlass);cab.position.set(.24*sc,.4*sc,0);g.add(cab);
      const arm=new THREE.Mesh(new THREE.BoxGeometry(.13*sc,1.65*sc,.14*sc),MAT.gold);arm.position.set(-.5*sc,.92*sc,0);arm.rotation.z=-.62;g.add(arm);
      const bucket=new THREE.Mesh(new THREE.BoxGeometry(.48*sc,.30*sc,.5*sc),MAT.gold);bucket.position.set(-1.0*sc,1.54*sc,.03);bucket.rotation.z=.25;g.add(bucket);
      world.add(g);
    }
    addExcavator([-2.8,-2.82,.9],1.0,.25);
    addExcavator([2.0,-2.74,2.5],.86,-.38);
    addExcavator([-1.0,-2.78,-1.0],.72,.48);

    // Small haul trucks in upper benches.
    function addTruck(x,y,z,s=.7){
      const g=new THREE.Group();g.position.set(x,y,z);
      const body=new THREE.Mesh(new THREE.BoxGeometry(1.7*s,.48*s,.95*s),MAT.gold);body.castShadow=true;g.add(body);
      const cab=new THREE.Mesh(new THREE.BoxGeometry(.52*s,.5*s,.75*s),MAT.blueGlass);cab.position.set(.5*s,.38*s,0);g.add(cab);
      for(let i=-1;i<=1;i+=2){const wheel=new THREE.Mesh(new THREE.CylinderGeometry(.18*s,.18*s,.15*s,14),MAT.dark);wheel.rotation.z=Math.PI/2;wheel.position.set(i*.55*s,-.23*s,.43*s);g.add(wheel);}
      g.traverse(o=>{if(o.userData){o.userData.type="equipment";}});world.add(g);
    }
    addTruck(-15,.2,-11.0,.75); addTruck(11,.2,10.5,.7); addTruck(-17,.15,9.5,.65);

    // Floating zone labels are HTML for crisp readability over the WebGL canvas.
    const labelEls={};
    Object.entries(zoneData).forEach(([name,data])=>{
      const el=document.createElement("div");
      const status=zoneStatuses[name]||"LOW";
      el.className=`mine-zone-label status-${status.toLowerCase()}`;
      el.innerHTML=`<span class="pin"></span><div><b>${data.label}</b><small>RISK: ${status}</small></div>`;
      labelsEl.appendChild(el); labelEls[name]=el;
    });

    function updateZoneStates(states){
      Object.entries(states || {}).forEach(([name,status])=>{
        zoneStatuses[name]=status;
        const g=zoneGroups[name];
        if(!g) return;
        const c=COLORS[status] || COLORS.LOW;
        const rings=g.children.filter(o=>o.isMesh && o.geometry?.type==="RingGeometry");
        const ring=rings[0], halo=rings[1];
        const pad=g.children.find(o=>o.isMesh && o.geometry?.type==="CylinderGeometry");
        if(ring?.material?.color) ring.material.color.setHex(c);
        if(halo?.material?.color) halo.material.color.setHex(c);
        if(pad?.material?.color) pad.material.color.setHex(c);
        if(pad?.material?.emissive) pad.material.emissive.setHex(c);
        const label=labelEls[name];
        if(label){
          label.classList.remove("status-low","status-medium","status-high","status-critical");
          label.classList.add(`status-${String(status).toLowerCase()}`);
          const small=label.querySelector("small");
          if(small) small.textContent=`RISK: ${status}`;
        }
      });
    }
    window.updateMineZoneStates=updateZoneStates;

    function updateLabels(){
      Object.entries(zoneData).forEach(([name,data])=>{
        const el=labelEls[name],g=zoneGroups[name]; if(!el||!g)return;
        const p=new THREE.Vector3(0,.62,0);g.localToWorld(p);p.project(camera);
        const x=(p.x*.5+.5)*viewport.clientWidth;
        const y=(-p.y*.5+.5)*viewport.clientHeight;
        const visible=p.z>-1&&p.z<1&&x>-80&&x<viewport.clientWidth+80&&y>-50&&y<viewport.clientHeight+50;
        el.style.transform=`translate3d(${x}px,${y}px,0)`;
        el.style.opacity=visible?"1":"0";
      });
    }

    const raycaster=new THREE.Raycaster();
    const pointer=new THREE.Vector2();
    let hover=null,selected=null;

    function statusText(text){const el=document.getElementById("map-interaction-status");if(el)el.textContent=text;}
    function resolveTarget(obj){
      let node=obj;
      while(node){
        if(node.userData && node.userData.hoverTarget) return node.userData.hoverTarget;
        node=node.parent;
      }
      return null;
    }
    function setHover(target){
      if(hover===target)return;
      if(hover?.userData?.type==="zone") labelEls[hover.userData.zone]?.classList.remove("is-hovered");
      hover=target;
      if(target){
        if(target.userData.type==="zone"){
          labelEls[target.userData.zone]?.classList.add("is-hovered");
          statusText(`${ZONE_CODES[target.userData.zone]} · ${zoneStatuses[target.userData.zone]||"LOW"} · ZONE`);
        } else statusText(`${target.userData.label} · STRUCTURE`);
      } else statusText("HOVER A ZONE OR STRUCTURE");
    }
    function pointerUpdate(e){
      const r=renderer.domElement.getBoundingClientRect();
      pointer.x=((e.clientX-r.left)/r.width)*2-1;
      pointer.y=-((e.clientY-r.top)/r.height)*2+1;
      raycaster.setFromCamera(pointer,camera);
      const hits=raycaster.intersectObjects(world.children,true);
      setHover(hits.length?resolveTarget(hits[0].object):null);
    }

    renderer.domElement.addEventListener("pointermove",e=>{
      pointerUpdate(e);
      if(dragging){ yaw+=(e.clientX-lastPointer.x)*.003; pitch=Math.max(-.48,Math.min(.02,pitch+(e.clientY-lastPointer.y)*.0022)); lastPointer={x:e.clientX,y:e.clientY}; }
    });
    renderer.domElement.addEventListener("pointerdown",e=>{dragging=true;lastPointer={x:e.clientX,y:e.clientY};renderer.domElement.setPointerCapture(e.pointerId);});
    renderer.domElement.addEventListener("pointerup",e=>{
      dragging=false;try{renderer.domElement.releasePointerCapture(e.pointerId);}catch{}
      pointerUpdate(e);
      if(hover?.userData?.type==="zone"){
        selected=hover;
        window.openZonePopup(hover.userData.zone,zoneStatuses[hover.userData.zone]||"LOW");
      }
    });
    renderer.domElement.addEventListener("pointerleave",()=>setHover(null));
    renderer.domElement.addEventListener("wheel",e=>{e.preventDefault();targetZoom=Math.max(.86,Math.min(1.22,targetZoom*(e.deltaY>0?.95:1.05)));},{passive:false});

    function focusZone(name){
      const g=zoneGroups[name];if(!g)return;
      selected=g;statusText(`${ZONE_CODES[name]||"Z-00"} · ${zoneStatuses[name]||"LOW"} · SELECTED`);
      window.openZonePopup(name,zoneStatuses[name]||"LOW");
    }
    window.focusMineZone=focusZone;
    document.getElementById("mine-reset-view")?.addEventListener("click",()=>{yaw=.48;pitch=-.26;targetZoom=1;selected=null;});
    document.getElementById("mine-zoom-in")?.addEventListener("click",()=>targetZoom=Math.min(1.22,targetZoom+.07));
    document.getElementById("mine-zoom-out")?.addEventListener("click",()=>targetZoom=Math.max(.86,targetZoom-.07));

    const clock=new THREE.Clock();
    function animate(){
      requestAnimationFrame(animate);
      const t=clock.getElapsedTime();
      world.rotation.y += (yaw-world.rotation.y)*.06;
      world.rotation.x += (pitch-world.rotation.x)*.06;
      world.scale.setScalar(targetZoom);
      camera.position.set(28/targetZoom,24/targetZoom,34/targetZoom);
      camera.lookAt(0,-.9,0);

      Object.values(zoneGroups).forEach(g=>{
        const isHover=g===hover, isSelected=g===selected;
        const targetY=g.userData.baseY+(isHover?.48:(isSelected?.12:0));
        g.position.y += (targetY-g.position.y)*.12;
        g.rotation.y += ((isHover?.10:0)-g.rotation.y)*.045;
        g.rotation.x += ((isHover?-.035:0)-g.rotation.x)*.045;
        const pulse=.68+.08*(Math.sin(t*1.5+(g.position.x*.08))+1)/2;
        const ring=g.children.find(c=>c.isMesh&&c.geometry?.type==="RingGeometry");
        if(ring?.material) ring.material.opacity=isHover||isSelected?.92:pulse;
        const halo=g.children.find(c=>c.isMesh&&c.geometry?.type==="RingGeometry"&&c!==ring);
        if(halo?.material) halo.material.opacity=(isHover?.13:.055);
      });

      if(hover?.userData?.type==="building"){
        const g=hover;
        g.position.y += (g.userData.baseY+.52-g.position.y)*.10;
        g.rotation.y += (g.userData.baseRot+.12-g.rotation.y)*.045;
        g.rotation.x += (-.025-g.rotation.x)*.045;
      }

      updateLabels();
      renderer.render(scene,camera);
    }

    function resize(){
      const r=viewport.getBoundingClientRect();
      renderer.setSize(r.width,r.height,false);
      camera.aspect=r.width/r.height;
      camera.updateProjectionMatrix();
    }
    new ResizeObserver(resize).observe(viewport);
    resize();
    if(loading) loading.classList.add("is-ready");
    animate();
  }
})();

/* --------------------------------------------------------------------------
 * AI operations layer: live simulation, model explanation, worker/equipment
 * telemetry, camera events, what-if analysis, evacuation, incident replay and
 * the prototype Safety Copilot.
 * -------------------------------------------------------------------------- */
(function initAICommandLayer() {
  const dashboard = document.querySelector('.world-dashboard');
  if (!dashboard) return;

  const riskColors = {LOW:'#42D67A', MEDIUM:'#D7B43A', HIGH:'#F0802C', CRITICAL:'#FF4D57'};
  const riskRank = {LOW:1, MEDIUM:2, HIGH:3, CRITICAL:4};
  const featureLabels = {
    methane:'Methane', co:'CO', temperature:'Temperature', humidity:'Humidity', dust:'Dust',
    vibration:'Vibration', noise:'Noise', worker_count:'Worker count', worker_hazard_distance:'Worker proximity',
    ppe_violations:'PPE violations', equipment_temperature:'Equipment temperature', equipment_overheating:'Overheating',
    equipment_health:'Equipment health', slope_stability:'Slope stability', wind_speed:'Wind speed',
    rainfall:'Rainfall', visibility:'Visibility'
  };

  let currentState = null;
  let riskHistory = [];
  let incidentCount = 0;
  let liveTimer = null;
  let selectedZone = 'Processing Area';
  let replayData = null;

  const $ = (id) => document.getElementById(id);
  const esc = (value) => {
    const el = document.createElement('div');
    el.textContent = value == null ? '' : String(value);
    return el.innerHTML;
  };

  function riskScoreFromClass(risk) { return ({LOW:12,MEDIUM:38,HIGH:68,CRITICAL:92}[risk] || 0); }

  function openModal(name) {
    const m = $(`${name}-modal`); if (!m) return;
    m.classList.add('is-open'); m.setAttribute('aria-hidden','false');
    if (name === 'copilot') {
      const zone = selectedZone || 'Processing Area';
      $('copilot-context').textContent = `Current focus: ${zone}`;
    }
  }
  function closeModal(name) {
    const m = $(`${name}-modal`); if (!m) return;
    m.classList.remove('is-open'); m.setAttribute('aria-hidden','true');
  }
  dashboard.querySelectorAll('[data-open]').forEach(btn => btn.addEventListener('click', () => openModal(btn.dataset.open)));
  document.querySelectorAll('[data-close]').forEach(btn =>
    btn.addEventListener('click', () => closeModal(btn.dataset.close))
);
  dashboard.querySelectorAll('.modal-overlay').forEach(m => m.addEventListener('click', (e) => { if (e.target === m) closeModal(m.id.replace('-modal','')); }));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') dashboard.querySelectorAll('.modal-overlay.is-open').forEach(m => closeModal(m.id.replace('-modal',''))); });

  function setText(id, value) { const el=$(id); if (el) el.textContent = value; }
  function riskColor(risk) { return riskColors[risk] || riskColors.LOW; }

  function updateKPIs(state) {
    const score = Number(state.mine_score || 0);
    setText('kpi-risk-value', `${Math.round(score)} / 100`);
    setText('kpi-risk-label', `${state.max_risk || 'LOW'} RISK`);
    setText('kpi-risk-trend', `${Math.round(Number(state.mine_probability || 0) * 100)}% AI`);
    setText('kpi-personnel', state.active_personnel ?? '—');
    setText('kpi-equipment', state.active_equipment ?? '—');
    setText('kpi-compliance', `${state.compliance ?? '—'}%`);
    setText('kpi-alerts', state.open_alerts ?? '—');
    const label=$('kpi-risk-label'); if(label) { label.style.color=riskColor(state.max_risk); label.style.borderColor=`${riskColor(state.max_risk)}55`; }
  }

  function updateZoneList(state) {
    const list=$('live-zone-list'); if(!list) return;
    [...list.querySelectorAll('[data-jump-zone]')].forEach(btn=>{
      const zone=btn.dataset.jumpZone, risk=state.zones?.[zone] || 'LOW';
      const dot=btn.querySelector('.status-dot'), b=btn.querySelector('b');
      if(dot){ dot.className=`status-dot bg-${risk.toLowerCase()}`; }
      if(b){ b.textContent=risk; b.style.color=riskColor(risk); }
    });
  }

  function updateExplanation(zone) {
    const obs=currentState?.observations?.[zone];
    if(!obs) return;
    selectedZone=zone;
    const risk=obs.ai_risk || currentState.zones?.[zone] || 'LOW';
    setText('explain-zone', zone.toUpperCase());
    setText('explain-risk', risk);
    setText('explain-confidence', `Confidence ${Number(obs.ai_confidence || 0).toFixed(1)}% · score ${Number(obs.ai_score || riskScoreFromClass(risk)).toFixed(0)}/100`);
    const list=$('factor-list'); if(!list) return;
    const factors=obs.top_factors || [];
    list.innerHTML=factors.length ? factors.map(f=>`<div class="factor-row"><span>${esc(featureLabels[f.feature] || f.feature)}</span><div class="factor-track"><i style="width:${Math.min(100, Math.max(2, Number(f.impact || 0)))}%"></i></div><b>${Number(f.impact || 0).toFixed(0)}%</b></div>`).join('') : '<div class="empty-state">No explanation available.</div>';
  }

  function updateWorkers(zone) {
    const obs=currentState?.observations?.[zone]; if(!obs) return;
    const count=Math.round(Number(obs.worker_count || 0));
    const risk=obs.ai_risk || 'LOW';
    const near=Math.max(0, Number(obs.worker_hazard_distance || 100));
    const atRisk=Math.max(0, Math.round(count * (riskRank[risk]-1) / 3 * .45));
    setText('worker-zone', zone);
    setText('worker-count', count);
    setText('worker-risk-count', atRisk);
    setText('worker-nearest', `${near.toFixed(1)} m`);
    const strip=$('worker-strip'); if(!strip) return;
    const n=Math.min(22, Math.max(8, Math.round(count/2)));
    strip.innerHTML=Array.from({length:n},(_,i)=>`<i class="worker-dot ${i<atRisk?'risk':''}" title="Worker ${i+1}"></i>`).join('');
  }

  function updateEquipment(zone) {
    const obs=currentState?.observations?.[zone]; if(!obs) return;
    const health=Math.round(Number(obs.equipment_health || 0));
    setText('equipment-health', `${health}%`);
    setText('equipment-overheat', Number(obs.equipment_overheating || 0) ? 'YES' : 'NO');
    setText('equipment-vibration', Number(obs.vibration || 0).toFixed(2));
    setText('equipment-health-state', health < 65 ? 'ATTENTION' : health < 80 ? 'WATCH' : 'NOMINAL');
    const bar=$('equipment-health-bar'); if(bar) bar.style.width=`${Math.max(4,Math.min(100,health))}%`;
  }

  function updateCamera(events) {
    if(!events?.length) return;
    const event=events.find(e=>e.severity !== 'INFO') || events[0];
    setText('camera-overlay', `${event.event.toUpperCase()} · ${event.confidence}% CONFIDENCE`);
    setText('camera-time', event.timestamp);
    setText('camera-event', `${event.camera} · ${event.zone} · ${event.event}`);
    const feed=$('camera-feed'); if(feed){ feed.classList.toggle('camera-critical', ['HIGH','CRITICAL'].includes(event.severity)); }
  }

  function updateRiskDistribution(state) {
    const counts={LOW:0,MEDIUM:0,HIGH:0,CRITICAL:0};
    Object.values(state.zones || {}).forEach(v => counts[v]=(counts[v]||0)+1);
    const high=counts.HIGH+counts.CRITICAL;
    setText('risk-donut-value', `${Math.round(Number(state.mine_score || 0))}`);
    const donut=$('risk-donut');
    if(donut){
      const total=Math.max(1,Object.keys(state.zones||{}).length);
      const p1=counts.CRITICAL/total*100, p2=(counts.CRITICAL+counts.HIGH)/total*100, p3=(counts.CRITICAL+counts.HIGH+counts.MEDIUM)/total*100;
      donut.style.background=`conic-gradient(#FF4D57 0 ${p1}%, #F0802C ${p1}% ${p2}%, #D7B43A ${p2}% ${p3}%, #42D67A ${p3}% 100%)`;
    }
    const list=$('risk-dist-list');
    if(list) list.innerHTML=`<span><i class="critical-dot"></i>High / Critical <b>${high}</b></span><span><i class="medium-dot"></i>Medium <b>${counts.MEDIUM}</b></span><span><i class="low-dot"></i>Low <b>${counts.LOW}</b></span>`;
  }

  function updateRiskHistory(score) {
    riskHistory.push(Number(score || 0)); if(riskHistory.length>12) riskHistory.shift();
    const bars=$('risk-history-bars'); if(!bars)return;
    bars.innerHTML=riskHistory.slice(-7).map(v=>`<i style="height:${Math.max(8,Math.min(96,v))}%"></i>`).join('');
    setText('risk-trend-value', Math.round(Number(score||0)));
  }

  function updateModelInfo(model) {
    if(!model)return;
    setText('model-rows', Number(model.rows || 0).toLocaleString());
    setText('model-accuracy', `${(Number(model.validation_balanced_accuracy || 0)*100).toFixed(1)}%`);
    setText('model-type-short', 'RF');
    setText('model-retrain', currentState?.timestamp || model.trained_at?.slice(11,19) || '—');
    setText('ai-model-name', model.model_type || 'Random Forest');
  }

  function updateIncident(state) {
    if(state.last_incident){
      if(!replayData || state.last_incident.id !== replayData.id){
        replayData=state.last_incident; incidentCount += 1;
        setText('incident-count', `${incidentCount} `);
      }
    }
  }

  async function poll() {
    try {
      const response=await fetch('/api/live_state',{cache:'no-store'});
      if(!response.ok) throw new Error(`HTTP ${response.status}`);
      const state=await response.json();
      currentState=state;
      const zone=selectedZone in (state.zones||{}) ? selectedZone : Object.keys(state.zones||{})[0];
      selectedZone=zone || 'Processing Area';
      Object.assign(window.zoneObservations || {}, state.observations || {});
      Object.assign(window.zoneStatuses || {}, state.zones || {});
      window.updateMineZoneStates?.(state.zones);
      updateKPIs(state); updateZoneList(state); updateExplanation(selectedZone); updateWorkers(selectedZone); updateEquipment(selectedZone);
      updateCamera(state.camera_events); updateRiskDistribution(state); updateRiskHistory(state.mine_score); updateModelInfo(state.model); updateIncident(state);
      const envScore=Math.max(20, Math.round(100 - Object.values(state.observations||{}).reduce((a,o)=>a + (Number(o.dust||0)/18 + Number(o.methane||0)*3 + Math.max(0,80-Number(o.visibility||10))*0.3),0)/Math.max(1,Object.keys(state.observations||{}).length)));
      setText('environment-value', `${envScore}%`); setText('environment-state', envScore<55?'Attention':envScore<75?'Watch':'Good'); const eb=$('environment-bar'); if(eb) eb.style.width=`${envScore}%`;
      if(Array.isArray(state.newly_critical) && state.newly_critical.length){ window.showToast?.('AI escalation', `${state.newly_critical.join(', ')} entered CRITICAL state.`, 'error'); }
    } catch(error) {
      console.error('AI live state error:',error);
      window.showToast?.('AI stream paused','Unable to refresh live telemetry. Retrying…','error');
    }
  }

  async function runWhatIf() {
    const zone=$('whatif-zone')?.value || selectedZone;
    const overrides={
      methane:Number($('whatif-methane')?.value || 1),
      temperature:Number($('whatif-temperature')?.value || 50),
      dust:Number($('whatif-dust')?.value || 70),
      worker_count:Number($('whatif-workers')?.value || 25),
      worker_hazard_distance:Number($('whatif-distance')?.value || 45),
      equipment_health:Number($('whatif-health')?.value || 90)
    };
    const resultBox=$('whatif-result');
    try{
      const r=await fetch('/api/what_if',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({zone,overrides})});
      const data=await r.json(); if(!r.ok) throw new Error(data.error || 'Simulation failed');
      resultBox.innerHTML=`<div class="scenario-risk" style="--risk:${riskColor(data.risk)}"><strong>${esc(data.risk)}</strong><span>${Number(data.confidence).toFixed(1)}% confidence · score ${Number(data.risk_score).toFixed(0)}/100</span></div><div class="scenario-probs">${Object.entries(data.distribution).map(([k,v])=>`<span><b>${k}</b><i style="width:${Number(v)*100}%"></i><em>${(Number(v)*100).toFixed(0)}%</em></span>`).join('')}</div><div class="scenario-note">Top contributors: ${(data.top_factors||[]).slice(0,3).map(f=>esc(featureLabels[f.feature]||f.feature)).join(', ')}.</div>`;
    }catch(e){ resultBox.textContent=e.message; }
  }
  $('run-whatif')?.addEventListener('click',runWhatIf);
  ['methane','temperature','dust','workers','distance','health'].forEach(name=>{
    const input=$(`whatif-${name}`),out=$(`whatif-${name}-out`); if(!input||!out)return;
    const update=()=>{ const suffix=name==='temperature'?'°C':name==='distance'?' m':name==='health'?'%':''; out.textContent=`${input.value}${suffix}`; };
    input.addEventListener('input',update); update();
  });

  async function runEvacuation(){
    const zone=$('evacuation-zone')?.value || selectedZone;
    const box=$('evacuation-result');
    try{ const r=await fetch('/api/evacuation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({zone})}); const d=await r.json(); if(!r.ok) throw new Error(d.error||'Failed');
      box.innerHTML=`<div class="evac-alert"><strong>${esc(d.risk)} · ${d.workers} WORKERS</strong><span>ETA ${Number(d.eta_minutes).toFixed(1)} min</span></div><div class="evac-route">${d.route.map((x,i)=>`<span>${esc(x)}</span>${i<d.route.length-1?'<b>↓</b>':''}`).join('')}</div><div class="emergency-services"><div><span>🚑 AMBULANCE</span><b>DISPATCH SIMULATED</b><em>ETA 06:20</em></div><div><span>🚒 FIRE RESPONSE</span><b>STANDBY</b><em>ETA 09:00</em></div></div>`;
    }catch(e){ box.textContent=e.message; }
  }
  $('run-evacuation')?.addEventListener('click',runEvacuation);

  async function loadReplay(){
    try{ const r=await fetch('/api/incident_replay',{cache:'no-store'}); const d=await r.json(); replayData=d; renderReplay(d); }catch(e){ window.showToast?.('Replay error',e.message,'error'); }
  }
  function renderReplay(data){
    setText('replay-summary',`${data.id} · ${data.zone} · ${data.severity}. ${data.summary}`);
    const tl=$('replay-timeline'); if(!tl)return;
    tl.innerHTML=(data.events||[]).map((ev,i)=>`<div class="replay-event" style="--delay:${i*120}ms"><span>${esc(ev.at)}</span><div><b>${esc(ev.event)}</b><small>${esc(ev.detail)}</small></div></div>`).join('');
  }
  $('replay-modal')?.addEventListener('transitionend',()=>{});
  const replayBtn=document.querySelector('[data-open="replay"]'); replayBtn?.addEventListener('click',loadReplay);
  $('replay-play')?.addEventListener('click',()=>{
    const events=[...document.querySelectorAll('.replay-event')]; events.forEach((el,i)=>{ el.classList.remove('play'); setTimeout(()=>el.classList.add('play'),i*460); });
  });
async function sendCopilot() {

  const input = $('copilot-question');
  const question = input?.value.trim();

  if (!question) return;

  const chat = $('copilot-chat');

  // Show the user's message immediately.
  chat.innerHTML += `
    <div class="copilot-msg user">
      ${esc(question)}
    </div>
  `;

  input.value = '';
  chat.scrollTop = chat.scrollHeight;

  try {

    const conversationId =
      localStorage.getItem('copilotConversationId') ||
      crypto.randomUUID();

    localStorage.setItem(
      'copilotConversationId',
      conversationId
    );

    const r = await fetch('/api/copilot', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        question,
        zone: selectedZone,
        conversation_id: conversationId
      })
    });

    // Handle normal HTTP errors before reading the stream.
    if (!r.ok) {
      let errorMessage = `HTTP ${r.status}`;

      try {
        const errorData = await r.json();
        errorMessage = errorData.error || errorMessage;
      } catch (_) {}

      throw new Error(errorMessage);
    }

    if (!r.body) {
      throw new Error('Streaming is not supported by this browser.');
    }

    // Create the bot message immediately.
    const botMessage = document.createElement('div');
    botMessage.className = 'copilot-msg bot';

    const botHeader = document.createElement('b');
    botHeader.textContent = `${selectedZone} · AI`;

    const botText = document.createElement('span');

    botMessage.appendChild(botHeader);
    botMessage.appendChild(botText);
    chat.appendChild(botMessage);

    // Read Ollama's streamed NDJSON response.
    const reader = r.body.getReader();
    const decoder = new TextDecoder();

    let buffer = '';
    let fullAnswer = '';

    while (true) {

      const { value, done } = await reader.read();

      if (done) break;

      buffer += decoder.decode(value, {
        stream: true
      });

      const lines = buffer.split('\n');

      // Keep the final incomplete line for the next chunk.
      buffer = lines.pop() || '';

      for (const line of lines) {

        if (!line.trim()) continue;

        let event;

        try {
          event = JSON.parse(line);
        } catch (parseError) {
          console.error(
            'Failed to parse streamed JSON:',
            line,
            parseError
          );
          continue;
        }

        // Streaming text from the backend.
        if (event.type === 'token') {

          fullAnswer += event.content || '';

          botText.textContent = fullAnswer;

          chat.scrollTop = chat.scrollHeight;
        }

        // Final metadata from the backend.
        else if (event.type === 'done') {

          botHeader.textContent =
            `${event.zone} · ${event.risk}`;

          botText.textContent =
            event.answer || fullAnswer;

          chat.scrollTop = chat.scrollHeight;
        }

        // Error generated inside the streaming backend.
        else if (event.type === 'error') {

          throw new Error(
            event.error || 'Copilot unavailable'
          );
        }
      }
    }

    // Process any final buffered line.
    if (buffer.trim()) {

      const event = JSON.parse(buffer);

      if (event.type === 'token') {

        fullAnswer += event.content || '';

        botText.textContent = fullAnswer;
      }

      else if (event.type === 'done') {

        botHeader.textContent =
          `${event.zone} · ${event.risk}`;

        botText.textContent =
          event.answer || fullAnswer;
      }

      else if (event.type === 'error') {

        throw new Error(
          event.error || 'Copilot unavailable'
        );
      }
    }

    chat.scrollTop = chat.scrollHeight;

  } catch (e) {

    chat.innerHTML += `
      <div class="copilot-msg bot error">
        ${esc(e.message)}
      </div>
    `;

    chat.scrollTop = chat.scrollHeight;
  }
}

  $('copilot-send')?.addEventListener('click',sendCopilot);
  $('copilot-question')?.addEventListener('keydown',e=>{if(e.key==='Enter')sendCopilot();});

  // Keep selection in sync with the 3D zone list and popup.
  dashboard.querySelectorAll('[data-jump-zone]').forEach(btn=>btn.addEventListener('click',()=>{
    selectedZone=btn.dataset.jumpZone; updateExplanation(selectedZone); updateWorkers(selectedZone); updateEquipment(selectedZone); setText('copilot-context',`Current focus: ${selectedZone}`);
  }));

  // Initial poll + regular live refresh.
  poll();
  liveTimer=setInterval(poll, 3500);
  window.addEventListener('beforeunload',()=>clearInterval(liveTimer));
})();
