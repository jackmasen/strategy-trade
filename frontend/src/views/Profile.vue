<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title"><el-icon><User /></el-icon>个人中心</h2>
        <div class="page-subtitle">修改个人资料、密码，绑定谷歌2FA</div>
      </div>
    </div>

    <el-row :gutter="18">
      <el-col :span="8">
        <div class="panel-card">
          <div class="panel-card__body" style="text-align:center;">
            <el-avatar :size="100" style="background:#1A382A;color:#25D07D;font-size:36px;">
              {{ user.displayName?.charAt(0)?.toUpperCase() }}
            </el-avatar>
            <h2 style="margin: 16px 0 6px;">{{ user.userInfo?.nickname }}</h2>
            <div class="text-dim">@{{ user.userInfo?.username }}</div>
            <el-tag style="margin-top: 10px;" size="default" effect="dark"
              :type="['success','warning','info'][user.userInfo?.role-1]">
              {{ ['超级管理员','运营','访客'][user.userInfo?.role-1] }}
            </el-tag>
            <el-divider />
            <div class="text-left" style="color:#B6C2CF; font-size:13px; line-height:2;">
              <div>📧 邮箱: {{ user.userInfo?.email || '-' }}</div>
              <div>📱 手机: {{ user.userInfo?.phone || '-' }}</div>
              <div>🔐 2FA: {{ user.userInfo?.two_factor_enabled ? '已启用' : '未启用' }}</div>
              <div>🕐 上次登录: {{ user.userInfo?.last_login_at || '-' }}</div>
              <div>📅 账号创建: {{ user.userInfo?.created_at }}</div>
            </div>
          </div>
        </div>
      </el-col>
      <el-col :span="16">
        <div class="panel-card mb-16">
          <div class="panel-card__header"><span class="panel-card__title">修改资料</span></div>
          <div class="panel-card__body">
            <el-form label-width="120px">
              <el-row :gutter="16">
                <el-col :span="12"><el-form-item label="昵称"><el-input v-model="form.nickname" /></el-form-item></el-col>
                <el-col :span="12"><el-form-item label="邮箱"><el-input v-model="form.email" /></el-form-item></el-col>
                <el-col :span="12"><el-form-item label="手机"><el-input v-model="form.phone" /></el-form-item></el-col>
              </el-row>
              <el-button type="primary" @click="save">保存修改</el-button>
            </el-form>
          </div>
        </div>
        <div class="panel-card mb-16">
          <div class="panel-card__header"><span class="panel-card__title">修改密码</span></div>
          <div class="panel-card__body">
            <el-form label-width="120px" @submit.prevent="changePwd">
              <el-row :gutter="16">
                <el-col :span="10"><el-form-item label="原密码"><el-input v-model="pwd.old" type="password" show-password /></el-form-item></el-col>
                <el-col :span="10"><el-form-item label="新密码"><el-input v-model="pwd.new" type="password" show-password /></el-form-item></el-col>
              </el-row>
              <el-button type="primary" @click="changePwd">修改密码</el-button>
            </el-form>
          </div>
        </div>
        <div class="panel-card">
          <div class="panel-card__header"><span class="panel-card__title">谷歌双重认证 (2FA)</span>
            <el-tag :type="user.userInfo?.two_factor_enabled?'success':'info'" effect="dark" style="margin-left:10px;">
              {{ user.userInfo?.two_factor_enabled ? '已启用' : '未启用' }}
            </el-tag>
          </div>
          <div class="panel-card__body">
            <el-alert type="warning" :closable="false" show-icon
              title="强烈建议开启2FA以保护API密钥和资金安全">
              <template #default>启用后，每次登录及敏感操作均需输入动态验证码</template>
            </el-alert>
            <div style="margin-top:18px;">
              <el-button :type="user.userInfo?.two_factor_enabled?'danger':'success'" size="large">
                {{ user.userInfo?.two_factor_enabled ? '关闭2FA' : '开启2FA配置向导' }}
              </el-button>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { User } from '@element-plus/icons-vue'
import { useUserStore } from '@/store/user'

const user = useUserStore()
const form = reactive({ nickname:'', email:'', phone:'' })
const pwd = reactive({ old:'', new:'' })

onMounted(async () => {
  try { await user.fetchMe() } catch (e) { /* 401 会被拦截器自动登出，不用重复提示 */ }
  Object.assign(form, {
    nickname: user.userInfo?.nickname || '',
    email: user.userInfo?.email || '',
    phone: user.userInfo?.phone || '',
  })
})

const save = async () => {
  try {
    const payload = { nickname: form.nickname, email: form.email, phone: form.phone }
    await user.updateProfile(payload)
    ElMessage.success('资料已更新')
  } catch (e) {
    ElMessage.error(e?.message || '保存失败，请重试')
  }
}

const changePwd = async () => {
  if (!pwd.old || !pwd.new) { return ElMessage.warning('请填写原密码和新密码') }
  if (pwd.new.length < 6) { return ElMessage.warning('新密码至少 6 位') }
  try {
    await user.changePassword(pwd.old, pwd.new)
    ElMessage.success('密码修改成功')
    pwd.old = ''; pwd.new = ''
  } catch (e) {
    // 错误已被拦截器提示，这里仅兜底
    ElMessage.error(e?.message || '密码修改失败，请检查原密码是否正确')
  }
}
</script>
