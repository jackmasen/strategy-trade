<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title"><el-icon><User /></el-icon>用户管理</h2>
        <div class="page-subtitle">管理系统用户、分配角色、重置密码（仅管理员）</div>
      </div>
      <el-button type="primary" size="large" :icon="Plus" @click="openCreate">新建用户</el-button>
    </div>

    <div class="filter-bar">
      <el-input v-model="kw" placeholder="搜索用户名/昵称/邮箱" style="width:280px;" :prefix-icon="Search" clearable />
      <el-select v-model="role" placeholder="角色" clearable style="width:140px;">
        <el-option label="超级管理员" :value="1" />
        <el-option label="运营" :value="2" />
        <el-option label="访客" :value="3" />
      </el-select>
      <el-select v-model="status" placeholder="状态" clearable style="width:140px;">
        <el-option label="启用" :value="1" />
        <el-option label="禁用" :value="0" />
      </el-select>
      <el-button :icon="RefreshRight" @click="load">刷新</el-button>
    </div>

    <div class="panel-card">
      <el-table :data="rows" :header-cell-style="{ background:'#192738' }">
        <el-table-column label="ID" prop="id" width="70" />
        <el-table-column label="头像" width="70" align="center">
          <template #default="{ row }">
            <el-avatar :size="36" style="background:#1A382A;color:#25D07D;">
              {{ (row.nickname || row.username)?.charAt(0)?.toUpperCase() }}
            </el-avatar>
          </template>
        </el-table-column>
        <el-table-column label="账号/昵称" min-width="160">
          <template #default="{ row }">
            <div class="text-strong">{{ row.username }}</div>
            <div class="text-dim" style="font-size:12px;">{{ row.nickname }}</div>
          </template>
        </el-table-column>
        <el-table-column label="邮箱" prop="email" width="200" />
        <el-table-column label="手机" prop="phone" width="140" />
        <el-table-column label="角色" width="130" align="center">
          <template #default="{ row }">
            <el-tag :type="['success','warning','info'][row.role-1]" effect="dark" size="small">
              {{ ['超级管理员','运营','访客'][row.role-1] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="2FA" width="90" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.two_factor_enabled" type="success" effect="dark" size="small">已启用</el-tag>
            <span v-else class="text-dim">未启用</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.status" :active-value="1" :inactive-value="0" @change="toggle(row)" />
          </template>
        </el-table-column>
        <el-table-column label="最后登录" width="180">
          <template #default="{ row }">
            <div>{{ row.last_login_at || '从未登录' }}</div>
            <div class="text-dim" style="font-size:11px;" v-if="row.last_login_ip">IP: {{ row.last_login_ip }}</div>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" prop="created_at" width="180" />
        <el-table-column label="操作" width="220" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" :icon="Edit" @click="edit(row)">编辑</el-button>
            <el-button link type="primary" size="small" :icon="Key" @click="resetPwd(row)">重置密码</el-button>
            <el-button link type="danger" size="small" :icon="Delete" @click="remove(row)" v-if="row.id !== 1">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 用户创建/编辑对话框 -->
    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑用户' : '新建用户'" width="520px" :close-on-click-modal="false">
      <el-form label-width="100px">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="用户名">
              <el-input v-model="userForm.username" :disabled="isEdit" placeholder="登录账号，创建后不可修改" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item v-if="!isEdit" label="初始密码">
              <el-input v-model="userForm.password" type="password" show-password placeholder="至少 6 位" />
            </el-form-item>
            <el-form-item v-else label="账号 ID">
              <el-input v-model="userForm.id" disabled />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="昵称"><el-input v-model="userForm.nickname" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="角色">
              <el-select v-model="userForm.role" style="width:100%">
                <el-option label="超级管理员" :value="1" />
                <el-option label="运营" :value="2" />
                <el-option label="访客" :value="3" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="邮箱"><el-input v-model="userForm.email" placeholder="user@example.com" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="手机"><el-input v-model="userForm.phone" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="状态">
              <el-radio-group v-model="userForm.status">
                <el-radio :value="1">启用</el-radio>
                <el-radio :value="0">禁用</el-radio>
              </el-radio-group>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm">{{ isEdit ? '保存修改' : '创建用户' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { User, Plus, Search, RefreshRight, Edit, Key, Delete } from '@element-plus/icons-vue'
import { http, API_PREFIX } from '@/utils/request'

const kw = ref('')
const role = ref()
const status = ref()
const rows = ref([])

// ========== 创建/编辑用户对话框 ==========
const dialogVisible = ref(false)
const isEdit = ref(false)
const userForm = reactive({
  id: null,
  username: '',
  password: '',
  nickname: '',
  email: '',
  phone: '',
  role: 3,
  status: 1,
})
const resetForm = () => Object.assign(userForm, {
  id: null, username: '', password: '', nickname: '',
  email: '', phone: '', role: 3, status: 1,
})

const openCreate = () => { resetForm(); isEdit.value = false; dialogVisible.value = true }
const edit = (row) => {
  isEdit.value = true
  Object.assign(userForm, {
    id: row.id,
    username: row.username,
    password: '',   // 编辑时不显示/修改密码字段（通过"重置密码"单独改）
    nickname: row.nickname || '',
    email: row.email || '',
    phone: row.phone || '',
    role: row.role,
    status: row.status,
  })
  dialogVisible.value = true
}

const submitForm = async () => {
  try {
    if (!isEdit.value) {
      if (!userForm.username || !userForm.password) return ElMessage.warning('请填写用户名和初始密码')
      if (userForm.password.length < 6) return ElMessage.warning('初始密码至少 6 位')
      await http.post(`${API_PREFIX}/users`, {
        username: userForm.username,
        password: userForm.password,
        nickname: userForm.nickname || userForm.username,
        email: userForm.email,
        phone: userForm.phone,
        role: userForm.role,
        status: userForm.status,
      })
      ElMessage.success('用户创建成功')
    } else {
      await http.put(`${API_PREFIX}/users/${userForm.id}`, {
        nickname: userForm.nickname,
        email: userForm.email,
        phone: userForm.phone,
        role: userForm.role,
        status: userForm.status,
      })
      ElMessage.success('用户信息已更新')
    }
    dialogVisible.value = false
    load()
  } catch (e) {
    ElMessage.error(e?.message || '保存失败')
  }
}

const load = async () => {
  try {
    const r = await http.get(`${API_PREFIX}/users`, { keyword: kw.value, role: role.value, status: status.value, page_size: 100 })
    rows.value = r.items || []
  } catch (e) { /* 拦截器已提示 */ }
}
const resetPwd = async (row) => {
  try {
    const { value } = await ElMessageBox.prompt(`重置用户 ${row.username} 的密码`, '重置密码', {
      inputType: 'password',
      inputValidator: (v) => v?.length >= 6 || '密码至少6位',
    })
    await http.put(`${API_PREFIX}/users/${row.id}`, { reset_password: value })
    ElMessage.success('密码已重置')
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.message || '密码重置失败')
  }
}
const toggle = async (row) => {
  const prev = row.status
  try {
    await http.put(`${API_PREFIX}/users/${row.id}`, { status: row.status })
    ElMessage.success('已更新')
  } catch (e) {
    row.status = prev   // UI 回滚
    ElMessage.error(e?.message || '状态更新失败')
  }
}
const remove = async (row) => {
  try {
    await ElMessageBox.confirm(`删除用户 ${row.username}？`, '确认', { type: 'warning' })
    await http.delete(`${API_PREFIX}/users/${row.id}`)
    ElMessage.success('删除成功')
    load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.message || '删除失败')
  }
}
onMounted(load)
</script>
