<template>
  <div class="login-page">
    <!-- 背景装饰 -->
    <div class="bg-grid"></div>
    <div class="bg-blur bg-blur--1"></div>
    <div class="bg-blur bg-blur--2"></div>

    <!-- 卡片 -->
    <div class="login-card">
      <div class="login-brand">
        <svg viewBox="0 0 48 48" width="54" height="54">
          <rect width="48" height="48" rx="12" fill="#0F1A24" stroke="#25D07D" stroke-width="2"/>
          <path d="M10 34 L18 22 L24 28 L34 14 L42 22" stroke="#25D07D" stroke-width="3.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <div>
          <h1 class="brand-title">策略交易系统</h1>
          <p class="brand-sub">Trading Strategy Management Platform</p>
        </div>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" size="large" @keyup.enter="onSubmit">
        <el-form-item prop="username">
          <el-input
            v-model="form.username"
            :prefix-icon="User"
            placeholder="请输入账号"
            autocomplete="username"
            clearable
          />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :prefix-icon="Lock"
            placeholder="请输入密码"
            autocomplete="current-password"
          />
        </el-form-item>

        <div class="tips-row">
          <div class="hint text-dim">
            <el-icon><InfoFilled /></el-icon>
            默认 admin / Admin@2024
          </div>
          <el-checkbox v-model="form.remember" size="small">记住我</el-checkbox>
        </div>

        <el-button
          type="primary"
          class="submit-btn"
          :loading="loading"
          native-type="submit"
          @click.prevent="onSubmit"
        >
          <el-icon><Right /></el-icon>
          <span>登录系统</span>
        </el-button>
      </el-form>

      <div class="login-footer text-dim">
        <span>© 2024 策略交易系统 · 支持币安 / OKX 子账号多策略</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock, InfoFilled, Right } from '@element-plus/icons-vue'
import { useUserStore } from '@/store/user'

const router = useRouter()
const route = useRoute()
const user = useUserStore()
const formRef = ref()
const loading = ref(false)

const form = reactive({
  username: 'admin',
  password: 'Admin@2024',
  remember: true,
})

const rules = {
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur', min: 6 }],
}

const onSubmit = async () => {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
    loading.value = true
    await user.login({ username: form.username, password: form.password })
    ElMessage.success('登录成功')
    const redirect = route.query.redirect || '/dashboard'
    router.replace(redirect)
  } catch (e) {
    // 拦截器已报提示
  } finally {
    loading.value = false
  }
}
</script>

<style lang="scss" scoped>
.login-page {
  width: 100vw;
  height: 100vh;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  background:
    radial-gradient(1000px 600px at 20% 20%, rgba(37, 208, 125, 0.08), transparent 60%),
    radial-gradient(800px 500px at 80% 80%, rgba(96, 165, 250, 0.07), transparent 60%),
    #0F1A24;
  overflow: hidden;
}
.bg-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(36, 52, 71, 0.4) 1px, transparent 1px),
    linear-gradient(90deg, rgba(36, 52, 71, 0.4) 1px, transparent 1px);
  background-size: 40px 40px;
  mask-image: radial-gradient(ellipse at center, black 40%, transparent 80%);
}
.bg-blur {
  position: absolute;
  border-radius: 50%;
  filter: blur(100px);
  opacity: .4;
  pointer-events: none;
}
.bg-blur--1 { width: 400px; height: 400px; top: -120px; left: -100px; background: #25D07D; }
.bg-blur--2 { width: 500px; height: 500px; bottom: -180px; right: -120px; background: #60A5FA; }

.login-card {
  position: relative;
  width: 420px;
  padding: 36px 38px 28px;
  background: rgba(21, 35, 48, 0.85);
  backdrop-filter: blur(16px);
  border: 1px solid #1E2E41;
  border-radius: 18px;
  box-shadow: 0 20px 60px rgba(0,0,0,.35);
  z-index: 2;
}
.login-brand {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 28px;
}
.brand-title {
  font-size: 22px;
  font-weight: 700;
  color: #F0F4F8;
  margin: 0;
  letter-spacing: 1px;
}
.brand-sub {
  margin: 4px 0 0;
  font-size: 12px;
  color: #6B7C90;
  letter-spacing: .5px;
}

.tips-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 6px 0 18px;
  font-size: 12px;
}
.hint {
  display: flex;
  align-items: center;
  gap: 4px;
  opacity: .7;
}

.submit-btn {
  width: 100%;
  height: 46px;
  font-size: 15px;
  font-weight: 600;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: linear-gradient(135deg, #25D07D 0%, #1AAD66 100%);
  border: none;
  box-shadow: 0 8px 24px rgba(37, 208, 125, 0.28);
  transition: all .2s;
  &:hover {
    transform: translateY(-1px);
    box-shadow: 0 12px 28px rgba(37, 208, 125, 0.38);
  }
  &:active { transform: translateY(0); }
}
.login-footer {
  margin-top: 22px;
  text-align: center;
  font-size: 12px;
}

/* 输入框内图标的颜色修复 */
:deep(.el-input__wrapper) {
  background: #0C151D !important;
  border: 1px solid #243447;
  box-shadow: none !important;
  border-radius: 10px;
  &:hover { border-color: #2F4A66; }
  &.is-focus { border-color: #25D07D; box-shadow: 0 0 0 2px rgba(37,208,125,.15) !important; }
}
:deep(.el-checkbox__inner) {
  background: #0C151D;
  border-color: #243447;
}
</style>
