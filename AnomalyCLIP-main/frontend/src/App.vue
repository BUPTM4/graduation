<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import axios from 'axios'
import { jsPDF } from 'jspdf'
import html2canvas from 'html2canvas'

// ==================== 数据状态 ====================

const uploadedFiles = ref([])
const uploadedImagePreviews = ref([])
const isDragging = ref(false)

const isLoading = ref(false)
const detectionResults = ref([])
const currentResultIndex = ref(0)

const showSettingsDialog = ref(false)

const detectionParams = reactive({
  threshold: 0.6
})

let pieChart = null
let particleCleanup = null

const animatedDefectRate = ref(0)
const animatedTotalCount = ref(0)
const animatedDefectCount = ref(0)
const isSystemReady = ref(false)
const detectionProgress = ref(0)
const detectionStatus = ref('')
const showResultAnimation = ref(false)

// 性能统计
const detectionFPS = ref(0)
const avgInferenceTime = ref(0)
const totalInferenceTime = ref(0)

// 状态提示语轮播
const statusMessages = [
  '正在分析纹理特征...',
  '提取视觉特征中...',
  '运行异常检测模型...',
  '生成热力图映射...',
  '计算缺陷概率...'
]
let statusInterval = null

// 缺陷率统计
const defectRate = computed(() => {
  if (detectionResults.value.length === 0) return 0
  const defectiveCount = detectionResults.value.filter(r => r.isDefective).length
  return ((defectiveCount / detectionResults.value.length) * 100).toFixed(1)
})

const API_BASE_URL = 'http://localhost:5000'

// ==================== 计算属性 ====================

const canDetect = computed(() => {
  return uploadedFiles.value.length > 0 && !isLoading.value
})

const canExport = computed(() => {
  return detectionResults.value.length > 0
})

// ==================== 动画函数 ====================

const animateNumber = (target, endValue, duration = 1000) => {
  const startValue = target.value
  const startTime = performance.now()
  
  const update = (currentTime) => {
    const elapsed = currentTime - startTime
    const progress = Math.min(elapsed / duration, 1)
    const easeProgress = 1 - Math.pow(1 - progress, 4)
    
    target.value = startValue + (endValue - startValue) * easeProgress
    
    if (progress < 1) {
      requestAnimationFrame(update)
    }
  }
  
  requestAnimationFrame(update)
}

watch(() => detectionResults.value.length, (newVal) => {
  animateNumber(animatedTotalCount, newVal)
})

watch(defectRate, (newVal) => {
  animateNumber(animatedDefectRate, parseFloat(newVal))
})

watch(() => detectionResults.value.filter(r => r.isDefective).length, (newVal) => {
  animateNumber(animatedDefectCount, newVal)
})

// ==================== 方法 ====================

const handleFileUpload = (uploadFile) => {
  const files = Array.isArray(uploadFile) ? uploadFile : [uploadFile]
  
  files.forEach(file => {
    const rawFile = file.raw || file
    if (!rawFile) return
    
    const allowedTypes = ['image/jpeg', 'image/png', 'image/bmp']
    if (!allowedTypes.includes(rawFile.type)) {
      ElMessage.error('仅支持 JPG、PNG、BMP 格式的图片')
      return
    }
    
    const fileIndex = uploadedFiles.value.length
    uploadedFiles.value.push(rawFile)
    uploadedImagePreviews.value.push(null)
    
    const reader = new FileReader()
    reader.onload = (e) => {
      uploadedImagePreviews.value[fileIndex] = e.target.result
    }
    reader.readAsDataURL(rawFile)
  })
  
  detectionResults.value = []
  showResultAnimation.value = false
}

const handleDrop = (event) => {
  event.preventDefault()
  isDragging.value = false
  
  const files = event.dataTransfer.files
  if (files.length > 0) {
    for (let i = 0; i < files.length; i++) {
      const file = files[i]
      const allowedTypes = ['image/jpeg', 'image/png', 'image/bmp']
      if (!allowedTypes.includes(file.type)) {
        ElMessage.error('仅支持 JPG、PNG、BMP 格式的图片')
        continue
      }
      
      const fileIndex = uploadedFiles.value.length
      uploadedFiles.value.push(file)
      uploadedImagePreviews.value.push(null)
      
      const reader = new FileReader()
      reader.onload = (e) => {
        uploadedImagePreviews.value[fileIndex] = e.target.result
      }
      reader.readAsDataURL(file)
    }
    
    detectionResults.value = []
    showResultAnimation.value = false
  }
}

const handleDragOver = (event) => {
  event.preventDefault()
  isDragging.value = true
}

const handleDragLeave = (event) => {
  event.preventDefault()
  isDragging.value = false
}

const clearAllFiles = () => {
  uploadedFiles.value = []
  uploadedImagePreviews.value = []
  detectionResults.value = []
  currentResultIndex.value = 0
  animatedTotalCount.value = 0
  animatedDefectCount.value = 0
  animatedDefectRate.value = 0
  showResultAnimation.value = false
  detectionFPS.value = 0
  avgInferenceTime.value = 0
  totalInferenceTime.value = 0
  
  if (pieChart) {
    pieChart.dispose()
    pieChart = null
  }
}

const startDetection = async () => {
  if (uploadedFiles.value.length === 0) {
    ElMessage.warning('请先上传图片')
    return
  }
  
  isLoading.value = true
  detectionResults.value = []
  detectionProgress.value = 0
  totalInferenceTime.value = 0
  showResultAnimation.value = false
  
  // 启动状态提示语轮播
  let statusIndex = 0
  detectionStatus.value = statusMessages[statusIndex]
  statusInterval = setInterval(() => {
    statusIndex = (statusIndex + 1) % statusMessages.length
    detectionStatus.value = statusMessages[statusIndex]
  }, 2000)
  
  try {
    const startTime = performance.now()
    
    for (let i = 0; i < uploadedFiles.value.length; i++) {
      const file = uploadedFiles.value[i]
      const imgStartTime = performance.now()
      
      const formData = new FormData()
      formData.append('file', file)
      formData.append('threshold', detectionParams.threshold)
      
      const response = await axios.post(`${API_BASE_URL}/api/detect`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data'
        },
        timeout: 60000
      })
      
      const data = response.data
      const imgEndTime = performance.now()
      const imgInferenceTime = (imgEndTime - imgStartTime) / 1000
      totalInferenceTime.value += imgInferenceTime
      
      detectionResults.value.push({
        anomalyScore: data.anomaly_score.toFixed(4),
        isDefective: data.is_anomalous,
        detectionTime: new Date().toLocaleString('zh-CN'),
        heatmap: data.heatmap,
        imagePreview: uploadedImagePreviews.value[i],
        inferenceTime: imgInferenceTime.toFixed(2)
      })
      
      detectionProgress.value = ((i + 1) / uploadedFiles.value.length) * 100
    }
    
    const endTime = performance.now()
    const totalTime = (endTime - startTime) / 1000
    detectionFPS.value = (uploadedFiles.value.length / totalTime).toFixed(1)
    avgInferenceTime.value = (totalInferenceTime.value / uploadedFiles.value.length).toFixed(2)
    
    clearInterval(statusInterval)
    detectionStatus.value = ''
    
    showResultAnimation.value = true
    updatePieChart()
    
    ElMessage.success(`检测完成，共检测 ${detectionResults.value.length} 张图片`)
  } catch (error) {
    console.error('检测失败:', error)
    clearInterval(statusInterval)
    detectionStatus.value = ''
    if (error.response) {
      ElMessage.error(error.response.data.error || '检测失败，请重试')
    } else if (error.code === 'ECONNABORTED') {
      ElMessage.error('请求超时，请检查后端服务是否运行')
    } else {
      ElMessage.error('检测失败，请检查后端服务是否运行')
    }
  } finally {
    isLoading.value = false
    detectionProgress.value = 0
  }
}

const openSettings = () => {
  showSettingsDialog.value = true
}

const confirmSettings = () => {
  showSettingsDialog.value = false
  ElMessage.success('参数已更新')
}

const exportPDF = async () => {
  if (detectionResults.value.length === 0) {
    ElMessage.warning('请先完成检测')
    return
  }
  
  try {
    ElMessage.info('正在生成PDF报告...')
    
    const pdf = new jsPDF({
      orientation: 'portrait',
      unit: 'mm',
      format: 'a4'
    })
    
    const pageWidth = pdf.internal.pageSize.getWidth()
    const pageHeight = pdf.internal.pageSize.getHeight()
    const margin = 15
    let yPos = margin
    
    const createTextElement = (text, fontSize = 12, isBold = false) => {
      const div = document.createElement('div')
      div.style.cssText = `
        position: absolute;
        left: -9999px;
        font-family: 'Microsoft YaHei', 'SimHei', sans-serif;
        font-size: ${fontSize}px;
        font-weight: ${isBold ? 'bold' : 'normal'};
        color: black;
        white-space: nowrap;
      `
      div.textContent = text
      document.body.appendChild(div)
      return div
    }
    
    const renderTextToPdf = async (text, x, y, fontSize = 12, isBold = false) => {
      const div = createTextElement(text, fontSize, isBold)
      try {
        const canvas = await html2canvas(div, { scale: 2, backgroundColor: null })
        const imgData = canvas.toDataURL('image/png')
        pdf.addImage(imgData, 'PNG', x, y, canvas.width / 7.56, canvas.height / 7.56)
      } finally {
        document.body.removeChild(div)
      }
    }
    
    await renderTextToPdf('纺织品缺陷检测报告', pageWidth / 2 - 40, yPos, 18, true)
    yPos += 12
    
    await renderTextToPdf(`检测时间: ${new Date().toLocaleString('zh-CN')}`, margin, yPos, 11)
    yPos += 7
    await renderTextToPdf(`检测图片总数: ${detectionResults.value.length} 张`, margin, yPos, 11)
    yPos += 7
    await renderTextToPdf(`缺陷图片数量: ${detectionResults.value.filter(r => r.isDefective).length} 张`, margin, yPos, 11)
    yPos += 7
    await renderTextToPdf(`缺陷率: ${defectRate.value}%`, margin, yPos, 11)
    yPos += 7
    await renderTextToPdf(`平均推理时间: ${avgInferenceTime.value}s`, margin, yPos, 11)
    yPos += 12
    
    for (let i = 0; i < detectionResults.value.length; i++) {
      const result = detectionResults.value[i]
      
      if (yPos > pageHeight - 70) {
        pdf.addPage()
        yPos = margin
      }
      
      await renderTextToPdf(`图片 ${i + 1}`, margin, yPos, 12, true)
      yPos += 6
      
      try {
        pdf.addImage(result.imagePreview, 'JPEG', margin, yPos, 55, 42)
      } catch (e) {
        console.error('添加图片失败:', e)
      }
      
      if (result.heatmap) {
        try {
          pdf.addImage(`data:image/png;base64,${result.heatmap}`, 'PNG', margin + 60, yPos, 55, 42)
        } catch (e) {
          console.error('添加热力图失败:', e)
        }
      }
      
      yPos += 46
      
      await renderTextToPdf(`异常分数: ${result.anomalyScore}`, margin, yPos, 10)
      yPos += 5
      await renderTextToPdf(`检测结果: ${result.isDefective ? '存在缺陷' : '正常'}`, margin, yPos, 10)
      yPos += 10
    }
    
    pdf.addPage()
    yPos = margin
    
    await renderTextToPdf('检测结果统计', pageWidth / 2 - 25, yPos, 16, true)
    yPos += 12
    
    const defectiveCount = detectionResults.value.filter(r => r.isDefective).length
    const normalCount = detectionResults.value.length - defectiveCount
    
    await renderTextToPdf(`缺陷图片: ${defectiveCount} 张 (${defectRate.value}%)`, margin, yPos, 11)
    yPos += 7
    await renderTextToPdf(`正常图片: ${normalCount} 张 (${(100 - parseFloat(defectRate.value)).toFixed(1)}%)`, margin, yPos, 11)
    yPos += 7
    await renderTextToPdf(`总缺陷率: ${defectRate.value}%`, margin, yPos, 11)
    yPos += 7
    await renderTextToPdf(`检测速度: ${detectionFPS.value} FPS`, margin, yPos, 11)
    
    pdf.save(`检测报告_${new Date().toISOString().slice(0, 10)}.pdf`)
    ElMessage.success('PDF报告导出成功')
  } catch (error) {
    console.error('PDF导出失败:', error)
    ElMessage.error('PDF导出失败，请重试')
  }
}

const initPieChart = () => {
  nextTick(() => {
    const chartDom = document.getElementById('pieChart')
    if (chartDom) {
      if (pieChart) {
        pieChart.dispose()
      }
      pieChart = echarts.init(chartDom, 'dark')
    }
  })
}

const updatePieChart = () => {
  nextTick(() => {
    if (detectionResults.value.length === 0) {
      if (pieChart) {
        pieChart.clear()
      }
      return
    }
    
    const chartDom = document.getElementById('pieChart')
    if (!chartDom) return
    
    if (pieChart) {
      pieChart.dispose()
      pieChart = null
    }
    pieChart = echarts.init(chartDom, 'dark')
    
    const defectiveCount = detectionResults.value.filter(r => r.isDefective).length
    const normalCount = detectionResults.value.length - defectiveCount
    
    const option = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        formatter: '{b}: {c}张 ({d}%)',
        backgroundColor: 'rgba(15, 23, 42, 0.95)',
        borderColor: 'rgba(14, 165, 233, 0.3)',
        textStyle: {
          color: '#E0E0E0'
        }
      },
      legend: {
        orient: 'vertical',
        left: 'left',
        top: 'center',
        textStyle: {
          color: '#E0E0E0',
          fontSize: 13
        },
        itemGap: 12
      },
      series: [
        {
          name: '检测结果',
          type: 'pie',
          radius: ['45%', '75%'],
          center: ['62%', '50%'],
          avoidLabelOverlap: false,
          itemStyle: {
            borderRadius: 6,
            borderColor: 'rgba(15, 23, 42, 0.8)',
            borderWidth: 3
          },
          label: {
            show: true,
            color: '#E0E0E0',
            fontSize: 12,
            fontWeight: 'bold',
            formatter: '{b}\n{d}%'
          },
          emphasis: {
            label: {
              show: true,
              fontSize: 14,
              fontWeight: 'bold'
            },
            itemStyle: {
              shadowBlur: 20,
              shadowOffsetX: 0,
              shadowColor: 'rgba(0, 0, 0, 0.5)'
            }
          },
          labelLine: {
            show: true,
            lineStyle: {
              color: 'rgba(224, 224, 224, 0.5)'
            }
          },
          data: [
            { value: defectiveCount, name: '缺陷', itemStyle: { color: '#ef4444' } },
            { value: normalCount, name: '正常', itemStyle: { color: '#10b981' } }
          ],
          animationType: 'scale',
          animationEasing: 'elasticOut',
          animationDelay: function (idx) {
            return Math.random() * 200
          }
        }
      ]
    }
    
    pieChart.setOption(option)
    pieChart.resize()
  })
}

const handleResize = () => {
  if (pieChart) {
    pieChart.resize()
  }
}

// 粒子背景动画
const initParticles = () => {
  const canvas = document.getElementById('particleCanvas')
  if (!canvas) return
  
  const ctx = canvas.getContext('2d')
  let particles = []
  let animationId = null
  
  const resizeCanvas = () => {
    canvas.width = window.innerWidth
    canvas.height = window.innerHeight
  }
  
  resizeCanvas()
  window.addEventListener('resize', resizeCanvas)
  
  class Particle {
    constructor() {
      this.reset()
    }
    
    reset() {
      this.x = Math.random() * canvas.width
      this.y = Math.random() * canvas.height
      this.size = Math.random() * 2 + 0.5
      this.speedX = (Math.random() - 0.5) * 0.3
      this.speedY = (Math.random() - 0.5) * 0.3
      this.opacity = Math.random() * 0.4 + 0.1
    }
    
    update() {
      this.x += this.speedX
      this.y += this.speedY
      
      if (this.x < 0 || this.x > canvas.width || this.y < 0 || this.y > canvas.height) {
        this.reset()
      }
    }
    
    draw() {
      ctx.beginPath()
      ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2)
      ctx.fillStyle = `rgba(14, 165, 233, ${this.opacity})`
      ctx.fill()
    }
  }
  
  for (let i = 0; i < 30; i++) {
    particles.push(new Particle())
  }
  
  const maxDistSq = 10000
  
  const animate = () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    
    particles.forEach(particle => {
      particle.update()
      particle.draw()
    })
    
    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const p1 = particles[i]
        const p2 = particles[j]
        const dx = p1.x - p2.x
        const dy = p1.y - p2.y
        const distSq = dx * dx + dy * dy
        
        if (distSq < maxDistSq) {
          const distance = Math.sqrt(distSq)
          ctx.beginPath()
          ctx.moveTo(p1.x, p1.y)
          ctx.lineTo(p2.x, p2.y)
          ctx.strokeStyle = `rgba(14, 165, 233, ${0.08 * (1 - distance / 100)})`
          ctx.lineWidth = 0.5
          ctx.stroke()
        }
      }
    }
    
    animationId = requestAnimationFrame(animate)
  }
  
  animate()
  
  particleCleanup = () => {
    cancelAnimationFrame(animationId)
    window.removeEventListener('resize', resizeCanvas)
  }
}

// ==================== 生命周期 ====================

onMounted(() => {
  initPieChart()
  initParticles()
  window.addEventListener('resize', handleResize)
  
  setTimeout(() => {
    isSystemReady.value = true
  }, 500)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  if (pieChart) {
    pieChart.dispose()
  }
  if (statusInterval) {
    clearInterval(statusInterval)
  }
  if (particleCleanup) {
    particleCleanup()
  }
})
</script>

<template>
  <div class="app-container">
    <!-- 科技感网格背景 -->
    <div class="grid-bg"></div>
    
    <!-- 粒子背景 -->
    <canvas id="particleCanvas" class="particle-bg"></canvas>
    
    <!-- 标题栏 -->
    <header class="header-bar">
      <div class="header-content">
        <div class="header-left">
          <div class="logo-icon">
            <div class="logo-ring"></div>
            <el-icon :size="26"><Monitor /></el-icon>
          </div>
          <div class="header-title-group">
            <div class="header-title">
              <span class="title-text">纺织品缺陷检测系统</span>
              <div class="title-glow"></div>
            </div>
            <div class="header-subtitle">Textile Defect Detection System</div>
          </div>
        </div>
        <div class="header-right">
          <div class="system-status" :class="{ ready: isSystemReady }">
            <span class="status-dot"></span>
            <span class="status-text">{{ isSystemReady ? '系统就绪' : '初始化中...' }}</span>
          </div>
          <span class="system-info">AnomalyCLIP 驱动</span>
          <el-button class="settings-btn" @click="openSettings">
            <el-icon><Setting /></el-icon>
            <span>设置</span>
          </el-button>
        </div>
      </div>
    </header>
    
    <!-- 核心区 -->
    <main class="core-area">
      <!-- 左侧栏 -->
      <div class="left-panel">
        <div class="upload-section glass-card">
          <div class="section-header">
            <div class="header-icon-wrapper">
              <el-icon><Upload /></el-icon>
            </div>
            <span>图片上传</span>
            <span class="header-badge">支持批量</span>
            <el-button 
              v-if="uploadedFiles.length > 0" 
              type="danger" 
              size="small" 
              text 
              @click="clearAllFiles"
            >
              清除全部
            </el-button>
          </div>
          <div 
            class="upload-area"
            :class="{ 'drag-over': isDragging }"
            @drop="handleDrop"
            @dragover="handleDragOver"
            @dragleave="handleDragLeave"
          >
            <el-upload
              class="upload-component"
              drag
              multiple
              :show-file-list="false"
              :auto-upload="false"
              accept=".jpg,.jpeg,.png,.bmp"
              :on-change="handleFileUpload"
            >
              <template v-if="uploadedImagePreviews.length === 0">
                <div class="upload-placeholder">
                  <div class="upload-icon-wrapper">
                    <el-icon class="upload-icon"><PictureFilled /></el-icon>
                    <div class="icon-ring"></div>
                  </div>
                  <div class="upload-text">拖拽图片到此处或点击上传</div>
                  <div class="upload-hint">支持 JPG、PNG、BMP 格式，可批量上传</div>
                </div>
              </template>
              <template v-else>
                <div class="preview-grid">
                  <div 
                    v-for="(preview, index) in uploadedImagePreviews" 
                    :key="index" 
                    class="preview-item"
                  >
                    <img :src="preview" class="preview-image" alt="预览图" />
                    <div class="preview-index">{{ index + 1 }}</div>
                  </div>
                </div>
              </template>
            </el-upload>
          </div>
          <div v-if="uploadedFiles.length > 0" class="file-count">
            <el-icon><Picture /></el-icon>
            <span>已选择 {{ uploadedFiles.length }} 张图片</span>
          </div>
        </div>
        
        <div class="detect-section">
          <el-button
            type="primary"
            size="large"
            class="detect-btn"
            :class="{ 'btn-ready': canDetect && !isLoading, 'btn-loading': isLoading }"
            :disabled="!canDetect"
            :loading="isLoading"
            @click="startDetection"
          >
            <template v-if="!isLoading">
              <el-icon class="btn-icon"><Search /></el-icon>
              <span>开始检测</span>
            </template>
            <template v-else>
              <span class="loading-text">{{ detectionStatus || '检测中...' }}</span>
            </template>
          </el-button>
          
          <!-- 检测进度条 -->
          <div v-if="isLoading" class="progress-container">
            <div class="progress-bar">
              <div class="progress-fill" :style="{ width: detectionProgress + '%' }"></div>
            </div>
            <div class="progress-text">{{ Math.round(detectionProgress) }}%</div>
          </div>
          
          <div class="detect-hint" v-if="canDetect && !isLoading">
            <el-icon><InfoFilled /></el-icon>
            <span>点击开始智能检测</span>
          </div>
        </div>
      </div>
      
      <!-- 右侧栏 -->
      <div class="right-panel glass-card">
        <div v-if="detectionResults.length === 0" class="result-placeholder">
          <div class="placeholder-content">
            <div class="placeholder-icon-wrapper">
              <el-icon class="placeholder-icon"><DataAnalysis /></el-icon>
              <div class="placeholder-ring"></div>
            </div>
            <div class="placeholder-text">检测结果将展示于此</div>
            <div class="placeholder-hint">请上传图片并点击"开始检测"</div>
          </div>
        </div>
        
        <div v-else class="result-display" :class="{ 'animate-in': showResultAnimation }">
          <div class="section-header">
            <div class="header-icon-wrapper">
              <el-icon><DataAnalysis /></el-icon>
            </div>
            <span>检测结果</span>
            <div class="result-nav">
              <el-button 
                size="small" 
                :disabled="currentResultIndex === 0"
                @click="currentResultIndex--"
              >
                <el-icon><ArrowLeft /></el-icon>
              </el-button>
              <span class="result-index">{{ currentResultIndex + 1 }} / {{ detectionResults.length }}</span>
              <el-button 
                size="small" 
                :disabled="currentResultIndex === detectionResults.length - 1"
                @click="currentResultIndex++"
              >
                <el-icon><ArrowRight /></el-icon>
              </el-button>
            </div>
          </div>
          
          <div class="image-section">
            <div class="image-box">
              <div class="image-label">
                <el-icon><Picture /></el-icon>
                <span>原始图片</span>
              </div>
              <div class="image-wrapper">
                <img :src="detectionResults[currentResultIndex].imagePreview" class="result-image" alt="原图" />
              </div>
            </div>
            <div class="image-box heatmap-box">
              <div class="image-label">
                <el-icon><DataLine /></el-icon>
                <span>缺陷热力图</span>
              </div>
              <div class="image-wrapper heatmap-wrapper">
                <img 
                  v-if="detectionResults[currentResultIndex].heatmap" 
                  :src="'data:image/png;base64,' + detectionResults[currentResultIndex].heatmap" 
                  class="result-image heatmap-image" 
                  alt="热力图" 
                />
                <div v-else class="no-heatmap">
                  <el-icon><Warning /></el-icon>
                  <span>暂无热力图</span>
                </div>
              </div>
              <!-- 热力图Colorbar -->
              <div class="colorbar">
                <div class="colorbar-gradient"></div>
                <div class="colorbar-labels">
                  <span>0.0</span>
                  <span>0.5</span>
                  <span>1.0</span>
                </div>
              </div>
            </div>
          </div>
          
          <div class="defect-info">
            <div class="info-header">
              <el-icon><InfoFilled /></el-icon>
              <span>检测信息</span>
            </div>
            <div class="info-grid">
              <div class="info-item">
                <span class="info-label">异常分数</span>
                <span class="info-value score">{{ detectionResults[currentResultIndex].anomalyScore }}</span>
              </div>
              <div class="info-item" :class="{ 'defective-bg': detectionResults[currentResultIndex].isDefective, 'normal-bg': !detectionResults[currentResultIndex].isDefective }">
                <span class="info-label">检测结果</span>
                <span class="info-value" :class="{ 'defective': detectionResults[currentResultIndex].isDefective, 'normal': !detectionResults[currentResultIndex].isDefective }">
                  {{ detectionResults[currentResultIndex].isDefective ? '存在缺陷' : '正常' }}
                </span>
              </div>
              <div class="info-item">
                <span class="info-label">推理时间</span>
                <span class="info-value time">{{ detectionResults[currentResultIndex].inferenceTime }}s</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
    
    <!-- 底部功能区 -->
    <footer class="bottom-area">
      <div class="stats-section glass-card">
        <div class="section-header">
          <div class="header-icon-wrapper">
            <el-icon><PieChart /></el-icon>
          </div>
          <span>检测结果统计</span>
        </div>
        <div class="stats-content">
          <div class="stats-overview">
            <div class="stat-item">
              <span class="stat-label">检测总数</span>
              <span class="stat-value">{{ Math.round(animatedTotalCount) }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">缺陷数量</span>
              <span class="stat-value defect">{{ Math.round(animatedDefectCount) }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">缺陷率</span>
              <span class="stat-value rate">{{ animatedDefectRate.toFixed(1) }}<span class="rate-unit">%</span></span>
            </div>
          </div>
          <div class="chart-container">
            <div v-if="detectionResults.length > 0" id="pieChart" class="pie-chart"></div>
            <div v-else class="no-chart">
              <el-icon class="no-chart-icon"><PieChart /></el-icon>
              <span>暂无检测数据</span>
            </div>
          </div>
        </div>
      </div>
      
      <!-- 性能看板 -->
      <div class="performance-section glass-card">
        <div class="section-header">
          <div class="header-icon-wrapper">
            <el-icon><TrendCharts /></el-icon>
          </div>
          <span>性能指标</span>
        </div>
        <div class="performance-content">
          <div class="perf-item">
            <span class="perf-label">检测速度</span>
            <span class="perf-value">{{ detectionFPS }} <span class="perf-unit">FPS</span></span>
          </div>
          <div class="perf-item">
            <span class="perf-label">平均推理</span>
            <span class="perf-value">{{ avgInferenceTime }} <span class="perf-unit">s</span></span>
          </div>
          <div class="perf-item">
            <span class="perf-label">模型</span>
            <span class="perf-value model">AnomalyCLIP</span>
          </div>
        </div>
      </div>
      
      <div class="export-section">
        <div class="export-card glass-card" :class="{ 'export-ready': canExport }">
          <div class="export-icon">
            <el-icon :size="28"><Download /></el-icon>
          </div>
          <div class="export-info">
            <div class="export-title">导出检测报告</div>
            <div class="export-desc">生成完整PDF报告</div>
          </div>
          <el-button
            type="primary"
            size="large"
            :disabled="!canExport"
            @click="exportPDF"
            class="export-btn"
          >
            导出报告
          </el-button>
        </div>
      </div>
    </footer>
    
    <!-- 设置弹窗 -->
    <el-dialog
      v-model="showSettingsDialog"
      title="检测参数设置"
      width="480px"
      class="settings-dialog"
      :close-on-click-modal="false"
    >
      <div class="settings-content">
        <div class="setting-item">
          <div class="setting-label">
            <el-icon><Aim /></el-icon>
            <span>缺陷检测阈值</span>
          </div>
          <div class="setting-control">
            <el-slider
              v-model="detectionParams.threshold"
              :min="0.1"
              :max="0.9"
              :step="0.05"
              :format-tooltip="(val) => val.toFixed(2)"
            />
            <span class="threshold-value">{{ detectionParams.threshold.toFixed(2) }}</span>
          </div>
          <div class="setting-hint">阈值越高，检测越严格，误报率降低但可能漏检</div>
        </div>
      </div>
      
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="showSettingsDialog = false">取消</el-button>
          <el-button type="primary" @click="confirmSettings">确认</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* ==================== 全局样式 ==================== */
html, body, #app {
  width: 100vw;
  min-height: 100vh;
  margin: 0;
  padding: 0;
  background: #0f172a;
  overflow-x: hidden;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

.app-container {
  width: 100%;
  min-height: 100vh;
  background: linear-gradient(180deg, #0f172a 0%, #1e293b 50%, #0f172a 100%);
  display: flex;
  flex-direction: column;
  color: #E0E0E0;
  position: relative;
}

/* ==================== 科技感网格背景 ==================== */
.grid-bg {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 0;
  background-image: 
    linear-gradient(rgba(14, 165, 233, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(14, 165, 233, 0.03) 1px, transparent 1px);
  background-size: 50px 50px;
}

/* ==================== 粒子背景 ==================== */
.particle-bg {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 1;
  opacity: 0.5;
}

/* ==================== 毛玻璃卡片效果 ==================== */
.glass-card {
  background: linear-gradient(145deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.8) 100%);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow: 
    0 8px 32px rgba(0, 0, 0, 0.3),
    inset 0 1px 0 rgba(255, 255, 255, 0.05);
  transition: all 0.4s ease;
}

.glass-card:hover {
  border-color: rgba(14, 165, 233, 0.3);
  box-shadow: 
    0 12px 40px rgba(0, 0, 0, 0.4),
    0 0 30px rgba(14, 165, 233, 0.1),
    inset 0 1px 0 rgba(255, 255, 255, 0.08);
}

/* ==================== 标题栏样式 ==================== */
.header-bar {
  height: 80px;
  background: linear-gradient(90deg, rgba(15, 23, 42, 0.95) 0%, rgba(30, 41, 59, 0.95) 50%, rgba(15, 23, 42, 0.95) 100%);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid rgba(14, 165, 233, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 32px;
  position: relative;
  z-index: 100;
}

.header-bar::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, rgba(14, 165, 233, 0.6), transparent);
}

.header-content {
  width: 100%;
  max-width: 1800px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 20px;
}

.logo-icon {
  width: 50px;
  height: 50px;
  background: linear-gradient(135deg, #0ea5e9 0%, #10b981 100%);
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  position: relative;
  box-shadow: 0 4px 20px rgba(14, 165, 233, 0.4);
}

.logo-ring {
  position: absolute;
  width: 100%;
  height: 100%;
  border-radius: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  animation: logoPulse 2s ease-in-out infinite;
}

@keyframes logoPulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.05); opacity: 0.7; }
}

.header-title-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.header-title {
  font-size: 24px;
  font-weight: 700;
  color: #FFFFFF;
  letter-spacing: 2px;
  position: relative;
}

.title-text {
  background: linear-gradient(135deg, #FFFFFF 0%, #94a3b8 50%, #FFFFFF 100%);
  background-size: 200% 100%;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  animation: titleShine 3s ease-in-out infinite;
}

@keyframes titleShine {
  0%, 100% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
}

.title-glow {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.1), rgba(16, 185, 129, 0.1));
  filter: blur(20px);
  z-index: -1;
  animation: glowPulse 2s ease-in-out infinite;
}

@keyframes glowPulse {
  0%, 100% { opacity: 0.3; }
  50% { opacity: 0.6; }
}

.header-subtitle {
  font-size: 11px;
  color: #64748b;
  letter-spacing: 1px;
  text-transform: uppercase;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.system-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 20px;
  border: 1px solid rgba(100, 116, 139, 0.3);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #64748b;
  transition: all 0.3s;
}

.system-status.ready .status-dot {
  background: #10b981;
  box-shadow: 0 0 10px rgba(16, 185, 129, 0.5);
  animation: statusBlink 2s ease-in-out infinite;
}

@keyframes statusBlink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.status-text {
  font-size: 12px;
  color: #64748b;
}

.system-status.ready .status-text {
  color: #10b981;
}

.system-info {
  font-size: 12px;
  color: #94a3b8;
  padding: 6px 14px;
  background: rgba(14, 165, 233, 0.1);
  border-radius: 20px;
  border: 1px solid rgba(14, 165, 233, 0.2);
}

.settings-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(14, 165, 233, 0.1);
  border: 1px solid rgba(14, 165, 233, 0.3);
  color: #0ea5e9;
  padding: 10px 18px;
  border-radius: 10px;
  font-size: 14px;
  transition: all 0.3s;
}

.settings-btn:hover {
  background: rgba(14, 165, 233, 0.2);
  border-color: #0ea5e9;
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(14, 165, 233, 0.3);
}

/* ==================== 核心区样式 ==================== */
.core-area {
  flex: 1;
  display: flex;
  padding: 24px;
  gap: 24px;
  min-height: 0;
  position: relative;
  z-index: 10;
}

.left-panel {
  width: 35%;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.upload-section {
  flex: 1;
  border-radius: 20px;
  padding: 24px;
  display: flex;
  flex-direction: column;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  font-size: 16px;
  font-weight: 600;
  color: #E0E0E0;
}

.header-icon-wrapper {
  width: 36px;
  height: 36px;
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.2), rgba(16, 185, 129, 0.2));
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.header-icon-wrapper .el-icon {
  color: #0ea5e9;
  font-size: 18px;
}

.header-badge {
  font-size: 11px;
  color: #10b981;
  background: rgba(16, 185, 129, 0.15);
  padding: 3px 10px;
  border-radius: 12px;
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.upload-area {
  flex: 1;
  border-radius: 16px;
  overflow: hidden;
  transition: all 0.3s;
}

.upload-area.drag-over {
  border: 2px dashed #0ea5e9;
  background: rgba(14, 165, 233, 0.05);
  box-shadow: 0 0 30px rgba(14, 165, 233, 0.2);
}

.upload-component {
  width: 100%;
  height: 100%;
}

.upload-component :deep(.el-upload) {
  width: 100%;
  height: 100%;
}

.upload-component :deep(.el-upload-dragger) {
  width: 100%;
  height: 100%;
  min-height: 300px;
  background: rgba(0, 0, 0, 0.2);
  border: 2px dashed rgba(148, 163, 184, 0.3);
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  transition: all 0.3s;
}

.upload-component :deep(.el-upload-dragger:hover) {
  border-color: #0ea5e9;
  background: rgba(14, 165, 233, 0.05);
}

.upload-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
}

.upload-icon-wrapper {
  position: relative;
  margin-bottom: 24px;
}

.upload-icon {
  font-size: 64px;
  color: #0ea5e9;
  opacity: 0.9;
  position: relative;
  z-index: 1;
}

.icon-ring {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 100px;
  height: 100px;
  border: 2px solid rgba(14, 165, 233, 0.3);
  border-radius: 50%;
  animation: ringExpand 2s ease-out infinite;
}

@keyframes ringExpand {
  0% { transform: translate(-50%, -50%) scale(0.8); opacity: 1; }
  100% { transform: translate(-50%, -50%) scale(1.3); opacity: 0; }
}

.upload-text {
  font-size: 17px;
  color: #E0E0E0;
  margin-bottom: 10px;
  font-weight: 500;
}

.upload-hint {
  font-size: 13px;
  color: #64748b;
}

.preview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(85px, 1fr));
  gap: 10px;
  padding: 10px;
  width: 100%;
  max-height: 100%;
  overflow-y: auto;
}

.preview-item {
  position: relative;
  aspect-ratio: 1;
  border-radius: 10px;
  overflow: hidden;
  background: rgba(0, 0, 0, 0.3);
  transition: all 0.3s;
  cursor: pointer;
}

.preview-item:hover {
  transform: scale(1.05);
  box-shadow: 0 4px 15px rgba(14, 165, 233, 0.3);
}

.preview-image {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.preview-index {
  position: absolute;
  bottom: 4px;
  right: 4px;
  background: linear-gradient(135deg, #0ea5e9, #10b981);
  color: white;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  font-weight: 600;
}

.file-count {
  margin-top: 14px;
  padding: 12px;
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.1), rgba(16, 185, 129, 0.1));
  border-radius: 10px;
  text-align: center;
  font-size: 14px;
  color: #0ea5e9;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 1px solid rgba(14, 165, 233, 0.2);
}

.detect-section {
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* ==================== 检测按钮脉冲动画 ==================== */
.detect-btn {
  width: 100%;
  height: 64px;
  font-size: 18px;
  font-weight: 700;
  border-radius: 16px;
  background: linear-gradient(135deg, #0ea5e9 0%, #10b981 100%);
  border: none;
  box-shadow: 0 4px 20px rgba(14, 165, 233, 0.3);
  transition: all 0.3s;
  position: relative;
  overflow: hidden;
}

.detect-btn::before {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.25), transparent);
  transition: left 0.5s;
}

.detect-btn.btn-ready {
  animation: btnPulse 2s ease-in-out infinite;
}

@keyframes btnPulse {
  0%, 100% { box-shadow: 0 4px 20px rgba(14, 165, 233, 0.3); }
  50% { box-shadow: 0 4px 30px rgba(14, 165, 233, 0.5), 0 0 40px rgba(16, 185, 129, 0.3); }
}

.detect-btn.btn-ready:hover::before {
  left: 100%;
}

.detect-btn.btn-ready:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 35px rgba(14, 165, 233, 0.5);
}

.detect-btn.btn-loading {
  animation: none;
}

.detect-btn:disabled {
  background: linear-gradient(135deg, #334155 0%, #1e293b 100%);
  box-shadow: none;
}

.btn-icon {
  margin-right: 8px;
}

.loading-text {
  font-size: 14px;
  animation: textFade 1.5s ease-in-out infinite;
}

@keyframes textFade {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

/* ==================== 进度条样式 ==================== */
.progress-container {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 10px;
}

.progress-bar {
  flex: 1;
  height: 6px;
  background: rgba(100, 116, 139, 0.3);
  border-radius: 3px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #0ea5e9, #10b981);
  border-radius: 3px;
  transition: width 0.3s ease;
  position: relative;
}

.progress-fill::after {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.3), transparent);
  animation: progressShine 1s linear infinite;
}

@keyframes progressShine {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}

.progress-text {
  font-size: 13px;
  color: #0ea5e9;
  font-weight: 600;
  min-width: 40px;
  text-align: right;
  font-family: 'Courier New', monospace;
}

.detect-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-size: 12px;
  color: #10b981;
  animation: hintPulse 2s ease-in-out infinite;
}

@keyframes hintPulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* ==================== 右侧栏 ==================== */
.right-panel {
  width: 65%;
  border-radius: 20px;
  padding: 24px;
  display: flex;
  flex-direction: column;
}

.result-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.placeholder-content {
  text-align: center;
  padding: 60px;
}

.placeholder-icon-wrapper {
  position: relative;
  margin-bottom: 28px;
}

.placeholder-icon {
  font-size: 80px;
  color: #334155;
  position: relative;
  z-index: 1;
}

.placeholder-ring {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 120px;
  height: 120px;
  border: 2px dashed rgba(14, 165, 233, 0.2);
  border-radius: 50%;
  animation: placeholderRotate 10s linear infinite;
}

@keyframes placeholderRotate {
  0% { transform: translate(-50%, -50%) rotate(0deg); }
  100% { transform: translate(-50%, -50%) rotate(360deg); }
}

.placeholder-text {
  font-size: 19px;
  color: #64748b;
  margin-bottom: 10px;
}

.placeholder-hint {
  font-size: 14px;
  color: #475569;
}

/* ==================== 结果展示动画 ==================== */
.result-display {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.result-display.animate-in {
  animation: slideInUp 0.6s ease-out;
}

@keyframes slideInUp {
  from {
    opacity: 0;
    transform: translateY(30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.result-nav {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 14px;
}

.result-index {
  font-size: 14px;
  color: #94a3b8;
  min-width: 60px;
  text-align: center;
  font-family: 'Courier New', monospace;
}

.image-section {
  flex: 1;
  display: flex;
  gap: 18px;
  min-height: 0;
}

.image-box {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 16px;
  padding: 14px;
  min-height: 0;
  border: 1px solid rgba(255, 255, 255, 0.05);
  transition: all 0.3s;
}

.image-box:hover {
  border-color: rgba(14, 165, 233, 0.2);
}

.heatmap-box {
  position: relative;
}

.image-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #94a3b8;
  margin-bottom: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.image-label .el-icon {
  color: #0ea5e9;
}

.image-wrapper {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  min-height: 0;
}

.result-image {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  border-radius: 10px;
  transition: transform 0.3s;
}

.result-image:hover {
  transform: scale(1.02);
}

.heatmap-wrapper {
  background: rgba(0, 0, 0, 0.3);
}

.no-heatmap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: #64748b;
}

.no-heatmap .el-icon {
  font-size: 36px;
}

/* ==================== 热力图Colorbar ==================== */
.colorbar {
  position: absolute;
  right: -30px;
  top: 50%;
  transform: translateY(-50%);
  width: 20px;
  height: 120px;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.colorbar-gradient {
  width: 12px;
  height: 100px;
  background: linear-gradient(to bottom, #ef4444, #f59e0b, #eab308, #22c55e, #0ea5e9);
  border-radius: 4px;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.colorbar-labels {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  height: 100px;
  margin-left: 4px;
  font-size: 10px;
  color: #64748b;
}

.defect-info {
  margin-top: 18px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 16px;
  padding: 18px;
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.info-header {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  font-weight: 600;
  color: #E0E0E0;
  margin-bottom: 14px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.info-header .el-icon {
  color: #0ea5e9;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px 16px;
  background: rgba(255, 255, 255, 0.02);
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.05);
  transition: all 0.3s;
}

.info-item:hover {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(14, 165, 233, 0.2);
}

.info-label {
  font-size: 12px;
  color: #64748b;
}

.info-value {
  font-size: 18px;
  color: #E0E0E0;
  font-weight: 700;
  font-family: 'Courier New', monospace;
}

.info-value.score {
  color: #0ea5e9;
}

.info-value.defective {
  color: #ef4444;
  text-shadow: 0 0 20px rgba(239, 68, 68, 0.4);
}

.info-value.normal {
  color: #10b981;
  text-shadow: 0 0 20px rgba(16, 185, 129, 0.4);
}

.info-item.defective-bg {
  background: rgba(239, 68, 68, 0.1);
  border-color: rgba(239, 68, 68, 0.3);
}

.info-item.normal-bg {
  background: rgba(16, 185, 129, 0.1);
  border-color: rgba(16, 185, 129, 0.3);
}

.info-value.time {
  font-size: 14px;
  color: #94a3b8;
  font-weight: 600;
}

/* ==================== 底部功能区样式 ==================== */
.bottom-area {
  background: linear-gradient(90deg, rgba(15, 23, 42, 0.95) 0%, rgba(30, 41, 59, 0.95) 50%, rgba(15, 23, 42, 0.95) 100%);
  backdrop-filter: blur(10px);
  border-top: 1px solid rgba(14, 165, 233, 0.2);
  padding: 20px 24px;
  display: flex;
  gap: 20px;
  min-height: 260px;
  flex-shrink: 0;
  position: relative;
  z-index: 10;
}

.bottom-area::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, rgba(14, 165, 233, 0.5), transparent);
}

.stats-section {
  flex: 2;
  border-radius: 16px;
  padding: 18px 22px;
  display: flex;
  flex-direction: column;
  height: 100%;
  box-sizing: border-box;
}

.stats-content {
  flex: 1;
  display: flex;
  gap: 24px;
  min-height: 0;
}

.stats-overview {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 16px;
  padding-right: 24px;
  border-right: 1px solid rgba(255, 255, 255, 0.1);
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.stat-label {
  font-size: 13px;
  color: #64748b;
}

.stat-value {
  font-size: 32px;
  font-weight: 700;
  color: #E0E0E0;
  font-family: 'Courier New', monospace;
}

.stat-value.defect {
  color: #ef4444;
  text-shadow: 0 0 20px rgba(239, 68, 68, 0.4);
}

.stat-value.rate {
  color: #0ea5e9;
  text-shadow: 0 0 20px rgba(14, 165, 233, 0.4);
}

.rate-unit {
  font-size: 16px;
  margin-left: 2px;
}

.chart-container {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 10px;
}

.pie-chart, #pieChart {
  width: 100%;
  height: 100%;
  min-height: 180px;
}

.no-chart {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #64748b;
}

.no-chart-icon {
  font-size: 40px;
  color: #334155;
}

.no-chart span {
  font-size: 13px;
}

/* ==================== 性能看板 ==================== */
.performance-section {
  flex: 1;
  min-width: 200px;
  max-width: 240px;
  border-radius: 16px;
  padding: 18px;
  display: flex;
  flex-direction: column;
}

.performance-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 14px;
}

.perf-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.perf-label {
  font-size: 12px;
  color: #64748b;
}

.perf-value {
  font-size: 20px;
  font-weight: 700;
  color: #0ea5e9;
  font-family: 'Courier New', monospace;
}

.perf-value.model {
  font-size: 14px;
  color: #10b981;
}

.perf-unit {
  font-size: 12px;
  color: #64748b;
  font-weight: 400;
}

.export-section {
  flex: 1;
  min-width: 300px;
  max-width: 360px;
}

.export-card {
  height: 100%;
  border-radius: 16px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  text-align: center;
  box-sizing: border-box;
}

.export-card.export-ready {
  border-color: rgba(14, 165, 233, 0.3);
}

.export-card.export-ready:hover {
  box-shadow: 0 8px 30px rgba(14, 165, 233, 0.2);
}

.export-icon {
  width: 56px;
  height: 56px;
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.2) 0%, rgba(16, 185, 129, 0.2) 100%);
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #0ea5e9;
  transition: all 0.3s;
}

.export-card.export-ready:hover .export-icon {
  transform: scale(1.1);
  box-shadow: 0 4px 20px rgba(14, 165, 233, 0.3);
}

.export-info {
  flex: 0;
}

.export-title {
  font-size: 16px;
  font-weight: 600;
  color: #E0E0E0;
  margin-bottom: 4px;
}

.export-desc {
  font-size: 12px;
  color: #64748b;
}

.export-btn {
  width: 100%;
  height: 44px;
  border-radius: 10px;
  font-weight: 600;
  background: linear-gradient(135deg, #0ea5e9 0%, #10b981 100%);
  border: none;
  transition: all 0.3s;
}

.export-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(14, 165, 233, 0.4);
}

/* ==================== 设置弹窗样式 ==================== */
.settings-dialog :deep(.el-overlay) {
  background-color: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(5px);
}

.settings-dialog :deep(.el-dialog) {
  background: linear-gradient(145deg, #1e293b 0%, #0f172a 100%) !important;
  border-radius: 20px !important;
  border: 1px solid rgba(14, 165, 233, 0.3) !important;
  box-shadow: 0 25px 80px rgba(0, 0, 0, 0.5) !important;
}

.settings-dialog :deep(.el-dialog__header) {
  padding: 22px 26px !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
  background: rgba(0, 0, 0, 0.2) !important;
  border-radius: 20px 20px 0 0 !important;
}

.settings-dialog :deep(.el-dialog__title) {
  color: #E0E0E0 !important;
  font-weight: 600 !important;
  font-size: 18px !important;
}

.settings-dialog :deep(.el-dialog__headerbtn) {
  top: 22px !important;
  right: 22px !important;
}

.settings-dialog :deep(.el-dialog__headerbtn .el-dialog__close) {
  color: #64748b !important;
  font-size: 20px !important;
}

.settings-dialog :deep(.el-dialog__headerbtn:hover .el-dialog__close) {
  color: #0ea5e9 !important;
}

.settings-dialog :deep(.el-dialog__body) {
  padding: 26px !important;
  background: transparent !important;
  color: #E0E0E0 !important;
}

.settings-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.setting-item {
  padding: 22px;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.setting-label {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 15px;
  font-weight: 600;
  color: #E0E0E0;
  margin-bottom: 18px;
}

.setting-label .el-icon {
  color: #0ea5e9;
  font-size: 18px;
}

.setting-control {
  display: flex;
  align-items: center;
  gap: 18px;
}

.setting-control :deep(.el-slider) {
  --el-slider-main-bg-color: #0ea5e9;
  --el-slider-runway-bg-color: rgba(100, 116, 139, 0.3);
}

.setting-control :deep(.el-slider__button) {
  border-color: #0ea5e9;
}

.setting-control :deep(.el-slider__bar) {
  background: linear-gradient(90deg, #0ea5e9, #10b981);
}

.threshold-value {
  min-width: 65px;
  text-align: center;
  font-size: 18px;
  font-weight: 700;
  color: #0ea5e9;
  padding: 10px 16px;
  background: rgba(14, 165, 233, 0.15);
  border-radius: 12px;
  border: 1px solid rgba(14, 165, 233, 0.3);
  font-family: 'Courier New', monospace;
}

.setting-hint {
  font-size: 13px;
  color: #64748b;
  margin-top: 14px;
  line-height: 1.6;
  padding: 12px 14px;
  background: rgba(14, 165, 233, 0.05);
  border-radius: 10px;
  border-left: 3px solid #0ea5e9;
}

.settings-dialog :deep(.el-dialog__footer) {
  padding: 18px 26px !important;
  border-top: 1px solid rgba(255, 255, 255, 0.1) !important;
  background: rgba(0, 0, 0, 0.2) !important;
  border-radius: 0 0 20px 20px !important;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 14px;
}

.dialog-footer :deep(.el-button) {
  padding: 12px 24px;
  border-radius: 10px;
  font-weight: 600;
}

.dialog-footer :deep(.el-button--primary) {
  background: linear-gradient(135deg, #0ea5e9 0%, #10b981 100%);
  border: none;
}

/* ==================== 响应式适配 ==================== */
@media (max-width: 1400px) {
  .performance-section {
    display: none;
  }
  
  .stats-section {
    flex: 3;
  }
}

@media (max-width: 1199px) and (min-width: 768px) {
  .core-area {
    flex-direction: column;
  }
  
  .left-panel {
    width: 100%;
    flex-direction: row;
    height: auto;
  }
  
  .upload-section {
    flex: 1;
  }
  
  .detect-section {
    width: 220px;
    flex: none;
  }
  
  .right-panel {
    width: 100%;
    flex: 1;
  }
  
  .bottom-area {
    flex-direction: column;
    min-height: auto;
    height: auto;
    padding: 20px 24px;
  }
  
  .stats-section,
  .export-section {
    width: 100%;
    max-width: none;
    min-height: 200px;
  }
  
  .stats-content {
    flex-direction: row;
  }
  
  .stats-overview {
    flex-direction: row;
    border-right: none;
    border-bottom: none;
    padding-right: 0;
    padding-bottom: 0;
  }
}

@media (max-width: 767px) {
  .core-area {
    flex-direction: column;
    padding: 16px;
  }
  
  .left-panel {
    width: 100%;
  }
  
  .right-panel {
    width: 100%;
  }
  
  .bottom-area {
    flex-direction: column;
    padding: 16px;
    min-height: auto;
    height: auto;
  }
  
  .stats-section,
  .export-section {
    width: 100%;
    max-width: none;
    min-height: 200px;
  }
  
  .header-title {
    font-size: 18px;
  }
  
  .image-section {
    flex-direction: column;
  }
  
  .info-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  
  .system-info {
    display: none;
  }
  
  .stats-content {
    flex-direction: column;
  }
  
  .stats-overview {
    flex-direction: row;
    justify-content: space-around;
    border-right: none;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    padding-right: 0;
    padding-bottom: 12px;
  }
  
  .colorbar {
    display: none;
  }
}
</style>
