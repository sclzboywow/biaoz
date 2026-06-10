<script setup lang="ts">
import { reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../../api'

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{ 'update:visible': [value: boolean]; created: [] }>()

const documentForm = reactive({ title: '', standard_no: '', category: '', issuing_authority: '' })

async function createDocument() {
  await api.post('/documents', documentForm)
  emit('update:visible', false)
  Object.assign(documentForm, { title: '', standard_no: '', category: '', issuing_authority: '' })
  ElMessage.success('文件台账已创建')
  emit('created')
}
</script>

<template>
  <el-dialog :model-value="visible" title="新增文件台账" width="640px" @update:model-value="emit('update:visible', $event)">
    <el-form label-width="96px" :model="documentForm">
      <el-form-item label="文件标题"><el-input v-model="documentForm.title" /></el-form-item>
      <el-form-item label="标准编号"><el-input v-model="documentForm.standard_no" /></el-form-item>
      <el-form-item label="分类"><el-input v-model="documentForm.category" /></el-form-item>
      <el-form-item label="发布单位"><el-input v-model="documentForm.issuing_authority" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:visible', false)">取消</el-button>
      <el-button type="primary" @click="createDocument">保存</el-button>
    </template>
  </el-dialog>
</template>
