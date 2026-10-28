const menuToggle=document.querySelector('#menuToggle');const sidebar=document.querySelector('#sidebar');menuToggle?.addEventListener('click',()=>sidebar?.classList.toggle('open'));document.querySelectorAll('.password-toggle').forEach(button=>button.addEventListener('click',()=>{const input=button.parentElement.querySelector('input');input.type=input.type==='password'?'text':'password';button.textContent=input.type==='password'?'Show':'Hide'}));

const dashboardAnalyticsElement=document.querySelector('#dashboardAnalytics');
if (dashboardAnalyticsElement && window.Chart) {
	const analytics=JSON.parse(dashboardAnalyticsElement.textContent);
	const trendSelector=document.querySelector('#trendPeriod');
	const trendCanvas=document.querySelector('#attendanceTrendChart');
	const initialTrend=analytics.trend_7;
	const trendChart=new Chart(trendCanvas, {
		type:'line',
		data:{
			labels:initialTrend.map(point=>point.label),
			datasets:[
				{label:'Present',data:initialTrend.map(point=>point.present),borderColor:'#1f785c',backgroundColor:'#1f785c',tension:0.25,yAxisID:'employees'},
				{label:'Absent',data:initialTrend.map(point=>point.absent),borderColor:'#d07965',backgroundColor:'#d07965',tension:0.25,yAxisID:'employees'},
				{label:'Attendance %',data:initialTrend.map(point=>point.percentage),borderColor:'#d49d45',backgroundColor:'#d49d45',borderDash:[5,4],tension:0.25,yAxisID:'percentage'},
			],
		},
		options:{
			responsive:true,
			maintainAspectRatio:false,
			interaction:{mode:'index',intersect:false},
			scales:{
				employees:{beginAtZero:true,position:'left',ticks:{precision:0},title:{display:true,text:'Employees'}},
				percentage:{beginAtZero:true,max:100,position:'right',grid:{drawOnChartArea:false},ticks:{callback:value=>`${value}%`}},
			},
		},
	});
	trendSelector?.addEventListener('change',()=>{
		const trend=trendSelector.value==='30'?analytics.trend_30:analytics.trend_7;
		trendChart.data.labels=trend.map(point=>point.label);
		trendChart.data.datasets[0].data=trend.map(point=>point.present);
		trendChart.data.datasets[1].data=trend.map(point=>point.absent);
		trendChart.data.datasets[2].data=trend.map(point=>point.percentage);
		trendChart.update();
	});
	const departments=analytics.departments;
	new Chart(document.querySelector('#departmentAttendanceChart'), {
		type:'bar',
		data:{
			labels:departments.map(item=>item.department),
			datasets:[
				{label:'Present',data:departments.map(item=>item.present),backgroundColor:'#1f785c'},
				{label:'Absent',data:departments.map(item=>item.absent),backgroundColor:'#d07965'},
			],
		},
		options:{
			indexAxis:'y',
			responsive:true,
			maintainAspectRatio:false,
			scales:{x:{beginAtZero:true,stacked:true,ticks:{precision:0}},y:{stacked:true}},
		},
	});
}

const activateCamera=document.querySelector('#activateCamera');
const cameraVideo=document.querySelector('#cameraVideo');
const cameraBadge=document.querySelector('#cameraBadge');
const cameraMessage=document.querySelector('#cameraMessage');
const recognitionStatus=document.querySelector('#recognitionStatus');
const cameraPlaceholder=document.querySelector('#cameraPlaceholder');
const captureAttendance=document.querySelector('#captureAttendance');
const startFaceEnrollment=document.querySelector('#startFaceEnrollment');
const cancelFaceEnrollment=document.querySelector('#cancelFaceEnrollment');
const enrollmentVideo=document.querySelector('#enrollmentVideo');
const enrollmentPlaceholder=document.querySelector('#enrollmentPlaceholder');
const enrollmentCameraBadge=document.querySelector('#enrollmentCameraBadge');
const enrollmentStatus=document.querySelector('#enrollmentStatus');
const enrollmentMessage=document.querySelector('#enrollmentMessage');
const recognitionConfig=document.querySelector('#recognitionConfig');
const currentAttendanceModeLabel=document.querySelector('#currentAttendanceMode');
const checkInModeButton=document.querySelector('#checkInMode');
const checkOutModeButton=document.querySelector('#checkOutMode');
const recognizedEmployee=document.querySelector('#recognizedEmployee');
const scanIntervalMs=Math.max(250,Number(recognitionConfig?.dataset.scanInterval)||1000);
let currentAttendanceMode='check_in';
let cameraStream;
let autoScanEnabled=false;
let scanInProgress=false;
let scanTimer;
let cooldownTimer;

function setAttendanceMode(mode) {
	currentAttendanceMode=mode;
	const checkInSelected=mode==='check_in';
	if (currentAttendanceModeLabel) currentAttendanceModeLabel.textContent=checkInSelected?'CHECK-IN':'CHECK-OUT';
	checkInModeButton?.classList.toggle('active',checkInSelected);
	checkInModeButton?.setAttribute('aria-pressed',String(checkInSelected));
	checkOutModeButton?.classList.toggle('active',!checkInSelected);
	checkOutModeButton?.setAttribute('aria-pressed',String(!checkInSelected));
	if (cameraMessage) cameraMessage.textContent=`${checkInSelected?'Check-in':'Check-out'} mode selected.`;
}

checkInModeButton?.addEventListener('click',()=>setAttendanceMode('check_in'));
checkOutModeButton?.addEventListener('click',()=>setAttendanceMode('check_out'));

function scheduleAutoScan(delay=scanIntervalMs) {
	if (!autoScanEnabled || scanTimer) return;
	scanTimer=window.setTimeout(() => {
		scanTimer=undefined;
		void scanForAttendance();
	}, delay);
}

let enrollmentStream;
let enrollmentTimer;
let enrollmentActive=false;
let enrollmentInProgress=false;

function scheduleEnrollment(delay=1000) {
	if (!enrollmentActive || enrollmentTimer) return;
	enrollmentTimer=window.setTimeout(() => {
		enrollmentTimer=undefined;
		void captureEnrollmentFrame();
	}, delay);
}

function stopEnrollmentCamera() {
	enrollmentActive=false;
	window.clearTimeout(enrollmentTimer);
	enrollmentTimer=undefined;
	enrollmentStream?.getTracks().forEach(track=>track.stop());
	enrollmentStream=undefined;
	enrollmentVideo.srcObject=null;
	enrollmentVideo.hidden=true;
	enrollmentPlaceholder.hidden=false;
	enrollmentCameraBadge.textContent='● Camera idle';
	startFaceEnrollment.hidden=false;
	startFaceEnrollment.disabled=false;
	cancelFaceEnrollment.hidden=true;
}

async function captureEnrollmentFrame() {
	if (!enrollmentActive || enrollmentInProgress) return;
	if (!enrollmentVideo.videoWidth) {
		scheduleEnrollment(250);
		return;
	}
	enrollmentInProgress=true;
	const canvas=document.createElement('canvas');
	canvas.width=enrollmentVideo.videoWidth;
	canvas.height=enrollmentVideo.videoHeight;
	canvas.getContext('2d').drawImage(enrollmentVideo, 0, 0, canvas.width, canvas.height);
	try {
		const image=await new Promise(resolve=>canvas.toBlob(resolve, 'image/jpeg', 0.9));
		if (!image) throw new Error('Unable to capture a camera frame.');
		const formData=new FormData();
		formData.append('employee_id', startFaceEnrollment.dataset.employeeId);
		formData.append('image', image, 'face-enrollment.jpg');
		const response=await fetch('/api/face/register', {method:'POST', body:formData});
		const result=await response.json();
		if (!response.ok && response.status===422 && result.message==='Exactly one face must be visible') {
			enrollmentStatus.textContent='Waiting for one face';
			enrollmentMessage.textContent='Keep one face centered in the frame.';
			return;
		}
		if (!response.ok) throw new Error(result.message || 'Face enrollment failed');
		enrollmentStatus.textContent='Face registered';
		enrollmentMessage.textContent='Face sample saved.';
		document.querySelector('#faceRegistrationStatus').textContent='Registered';
		document.querySelector('#faceRegistrationStatus').className='status active';
		startFaceEnrollment.innerHTML='Replace face sample <span>→</span>';
		stopEnrollmentCamera();
		enrollmentCameraBadge.textContent='● Face registered';
	} catch (error) {
		enrollmentStatus.textContent='Enrollment paused';
		enrollmentMessage.textContent=error.message;
		stopEnrollmentCamera();
	} finally {
		enrollmentInProgress=false;
		if (enrollmentActive) scheduleEnrollment();
	}
}

startFaceEnrollment?.addEventListener('click', async () => {
	if (!navigator.mediaDevices?.getUserMedia) {
		enrollmentMessage.textContent='Camera access requires a modern browser on localhost or HTTPS.';
		return;
	}
	startFaceEnrollment.disabled=true;
	try {
		enrollmentStream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'user'},audio:false});
		enrollmentVideo.srcObject=enrollmentStream;
		enrollmentVideo.style.cssText='height:100%;object-fit:cover;width:100%';
		enrollmentVideo.hidden=false;
		enrollmentPlaceholder.hidden=true;
		enrollmentCameraBadge.textContent='● Camera active';
		enrollmentStatus.textContent='Looking for a face';
		enrollmentMessage.textContent='Keep one face centered in the frame.';
		startFaceEnrollment.hidden=true;
		cancelFaceEnrollment.hidden=false;
		enrollmentActive=true;
		scheduleEnrollment(500);
	} catch (error) {
		startFaceEnrollment.disabled=false;
		enrollmentMessage.textContent=error.name==='NotAllowedError'?'Camera permission was denied. Allow camera access and try again.':'Unable to access the camera.';
	}
});

cancelFaceEnrollment?.addEventListener('click', () => {
	stopEnrollmentCamera();
	enrollmentStatus.textContent='Enrollment canceled';
	enrollmentMessage.textContent='Position one face in the frame.';
});

async function scanForAttendance() {
	if (!autoScanEnabled || scanInProgress || !cameraVideo.srcObject) return;
	if (!cameraVideo.videoWidth) {
		scheduleAutoScan(250);
		return;
	}
	scanInProgress=true;
	const canvas=document.createElement('canvas');
	canvas.width=cameraVideo.videoWidth;
	canvas.height=cameraVideo.videoHeight;
	canvas.getContext('2d').drawImage(cameraVideo, 0, 0, canvas.width, canvas.height);
	try {
		const image=await new Promise(resolve=>canvas.toBlob(resolve, 'image/jpeg', 0.9));
		if (!image) throw new Error('Unable to capture a camera frame.');
		const formData=new FormData();
		formData.append('image', image, 'camera-capture.jpg');
		formData.append('mode', currentAttendanceMode);
		const response=await fetch('/api/face/recognize', {method:'POST', body:formData});
		const result=await response.json();
		if (response.status===404 && ['Unknown face', 'No employee face samples are registered'].includes(result.message)) {
			recognitionStatus.textContent='Face not found';
			cameraMessage.textContent=`${result.message==='Unknown face'?'No registered face matched.':'No employee face samples are registered yet.'} Scanning continues automatically.`;
			return;
		}
		if (!response.ok && response.status===422 && result.message==='Exactly one face must be visible') {
			recognitionStatus.textContent='Waiting for one face';
			cameraMessage.textContent='Keep one face centered in the camera frame.';
			return;
		}
		if (response.status===429 && result.action==='cooldown') {
			autoScanEnabled=false;
			recognitionStatus.textContent='Cooldown';
			cameraBadge.textContent='● Cooldown active';
			if (recognizedEmployee) {
				recognizedEmployee.hidden=false;
				recognizedEmployee.textContent=`${result.employee.name} · ${result.employee.id}`;
			}
			cameraMessage.textContent=result.message;
			captureAttendance.hidden=false;
			captureAttendance.disabled=true;
			const cooldownEnds=Date.now()+Math.max(1,result.cooldown_remaining)*1000;
			const updateCooldown=()=>{
				const secondsLeft=Math.max(0,Math.ceil((cooldownEnds-Date.now())/1000));
				if (secondsLeft===0) {
					window.clearTimeout(cooldownTimer);
					captureAttendance.disabled=false;
					captureAttendance.innerHTML='Scan next person <span>→</span>';
					cameraMessage.textContent='Cooldown complete. Scan the next person when ready.';
					return;
				}
				captureAttendance.textContent=`Wait ${secondsLeft}s`;
				cooldownTimer=window.setTimeout(updateCooldown,1000);
			};
			updateCooldown();
			return;
		}
		if (response.status===409 && result.action) {
			autoScanEnabled=false;
			recognitionStatus.textContent={
				already_checked_in:'Already Checked In',
				check_in_required:'Check-in Required',
				already_complete:'Already Completed',
			}[result.action] || 'Attendance Not Changed';
			cameraBadge.textContent='● Face matched';
			if (recognizedEmployee) {
				recognizedEmployee.hidden=false;
				recognizedEmployee.textContent=`${result.employee.name} · ${result.employee.id}`;
			}
			cameraMessage.textContent=result.message;
			captureAttendance.hidden=false;
			captureAttendance.disabled=false;
			captureAttendance.innerHTML='Scan next person <span>→</span>';
			return;
		}
		if (!response.ok) throw new Error(result.message || 'Recognition failed');
		autoScanEnabled=false;
		const attendance=result.attendance || {};
		const time=result.action==='check_out' ? attendance.check_out : attendance.check_in;
		const timestamp=[attendance.date, time].filter(Boolean).join(' ');
		recognitionStatus.textContent=result.action==='check_out'?'Check-out recorded':'Check-in recorded';
		cameraBadge.textContent='● Attendance recorded';
		if (recognizedEmployee) {
			recognizedEmployee.hidden=false;
			recognizedEmployee.textContent=`${result.employee.name} · ${result.employee.id}`;
		}
		cameraMessage.textContent=`${result.message} · ${timestamp} · ${Math.round(result.confidence * 100)}% confidence`;
		captureAttendance.hidden=false;
		captureAttendance.disabled=false;
		captureAttendance.innerHTML='Scan next person <span>→</span>';
	} catch (error) {
		autoScanEnabled=false;
		recognitionStatus.textContent='Recognition paused';
		cameraMessage.textContent=error.message;
		captureAttendance.hidden=false;
		captureAttendance.disabled=false;
		captureAttendance.innerHTML='Try again <span>↻</span>';
	} finally {
		scanInProgress=false;
		if (autoScanEnabled) scheduleAutoScan();
	}
}

activateCamera?.addEventListener('click', async () => {
	if (!navigator.mediaDevices?.getUserMedia) {
		cameraMessage.textContent='Camera access is unavailable. Open the app in a modern browser on localhost or HTTPS.';
		recognitionStatus.textContent='Camera unavailable';
		return;
	}
	activateCamera.disabled=true;
	activateCamera.textContent='Requesting camera...';
	try {
		cameraStream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'user'},audio:false});
		cameraVideo.srcObject=cameraStream;
		cameraVideo.style.cssText='height:100%;object-fit:cover;width:100%';
		cameraVideo.hidden=false;
		cameraPlaceholder.hidden=true;
		cameraBadge.textContent='● Camera active';
		recognitionStatus.textContent='Looking for a face';
		cameraMessage.textContent=`Automatic ${currentAttendanceMode.replace('_',' ')} scan is active. Keep one face centered in the frame.`;
		activateCamera.textContent='Camera active';
		autoScanEnabled=true;
		scheduleAutoScan(500);
	} catch (error) {
		const message=error.name==='NotAllowedError'?'Camera permission was denied. Allow camera access in your browser settings and try again.':error.name==='NotFoundError'?'No camera was found on this device.':'Unable to access the camera. Check that another app is not using it.';
		cameraMessage.textContent=message;
		recognitionStatus.textContent='Camera unavailable';
		activateCamera.disabled=false;
		activateCamera.innerHTML='Try again <span>↻</span>';
	}
});

	captureAttendance?.addEventListener('click', () => {
	if (!cameraStream || autoScanEnabled) return;
	cameraBadge.textContent='● Camera active';
	captureAttendance.hidden=true;
	if (recognizedEmployee) recognizedEmployee.hidden=true;
	recognitionStatus.textContent='Looking for a face';
	cameraMessage.textContent=`Automatic ${currentAttendanceMode.replace('_',' ')} scan is active. Keep one face centered in the frame.`;
	autoScanEnabled=true;
	scheduleAutoScan();
});

window.addEventListener('pagehide',()=>{
	autoScanEnabled=false;
	window.clearTimeout(scanTimer);
	window.clearTimeout(cooldownTimer);
	cameraStream?.getTracks().forEach(track=>track.stop());
	stopEnrollmentCamera();
});
