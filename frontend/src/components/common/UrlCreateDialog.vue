<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../../api'

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{ 'update:visible': [value: boolean] }>()

const urlForm = reactive({
  url: '',
  source_name: '',
  source_unit: '',
  source_type: '文件直链',
  category: '标准规范',
  check_frequency: 'manual',
})

async function createUrlSource() {
  await api.post('/url-sources', urlForm)
  emit('update:visible', false)
  Object.assign(urlForm, {
    url: '',
    source_name: '',
    source_unit: '',
    source_type: '文件直链',
    category: '标准规范',
    check_frequency: 'manual',
  })
  ElMessage.success('URL 来源已创建')
}
</script>

<template>
  <el-dialog :model-value="visible" title="新增 URL 来源" width="640px" @update:model-value="emit('update:visible', $event)">
    <el-form label-width="96px" :model="urlForm">
      <el-form-item label="URL"><el-input v-model="urlForm.url" /></el-form-item>
      <el-form-item label="来源名称"><el-input v-model="urlForm.source_name" /></el-form-item>
      <el-form-item label="来源单位"><el-input v-model="urlForm.source_unit" /></el-form-item>
      <el-form-item label="来源类型">
        <el-select v-model="urlForm.source_type">
          <el-option label="文件直链" value="文件直链" />
          <el-option label="公告页面" value="公告页面" />
          <el-option label="目录页面" value="目录页面" />
        </el-select>
      </el-form-item>
      <el-form-item label="检查频率">
        <el-select v-model="urlForm.check_frequency">
          <el-option label="manual" value="manual" />
          <el-option label="daily" value="daily" />
          <el-option label="weekly" value="weekly" />
          <el-option label="monthly" value="monthly" />
        </el-select>
      </el-form-item>
      <el-form-item label="分类"><el-input v-model="urlForm.category" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:visible', false)">取消</el-button>
      <el-button type="primary" @click="createUrlSource">保存</el-button>
    </template>
  </el-dialog>
</template>
