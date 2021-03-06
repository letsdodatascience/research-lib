
#################################################
### THIS FILE WAS AUTOGENERATED! DO NOT EDIT! ###
#################################################
# file to edit: dev_nb/08a_cnn_hooks.ipynb

from lib.nb_07 import *

def normalize_to(train, valid):
    m,s = train.mean(),train.std()
    return normalize(train, m, s), normalize(valid, m, s)

class Lambda(nn.Module):

    def __init__(self, func):
        super().__init__()
        self.func = func

    def forward(self,x):
        return self.func(x)

def flatten(x): return x.view(x.shape[0], -1)

def mnist_resize(x): return x.view(-1, 1, 28, 28)

def cos_1cycle_anneal(start, high, end):
    return [sched_cos(start, high), sched_cos(high, end)]

def conv_layer(ni, nf, ks=3, stride=2):
    return nn.Sequential(nn.Conv2d(ni,nf,ks, padding=ks//2, stride=stride), nn.ReLU())

class BatchTransformXCallback(Callback):
    _order = 2

    def __init__(self, tfm): self.tfm = tfm
    def begin_batch(self): self.run.xb = self.tfm(self.run.xb)

def view_tfm(*size):
    def _inner(x): return x.view(*((-1,)+size))
    return _inner

def get_basic_cnn_learner(model, data, loss_func, opt_func=adam_opt(), lr=1e-2):
    cbs = [partial(AvgStatsCallback,accuracy),
       partial(CudaCallback, get_device()),
       Recorder,
       partial(BatchTransformXCallback, mnist_resize),
       #partial(SaveModelCallback, every="improvement", savename="basic_seq2seq_model"),
       #partial(GradientClipping, clip=0.1),
       ProgressCallback]

    lr = lr

    sched_lr  = combine_scheds([0.3,0.7], cos_1cycle_anneal(lr/10., lr, lr/1e5))
    sched_mom = combine_scheds([0.3,0.7], cos_1cycle_anneal(0.8, 0.7, 0.8))
    cbsched = [ParamScheduler('lr', sched_lr) , ParamScheduler('mom', sched_mom)]

    return Learner(model, data, loss_func=loss_func, cb_funcs=cbs, opt_func=adam_opt()), cbsched

def children(m):
    return list(m.children())

class Hook():
    def __init__(self, m, f): self.hook = m.register_forward_hook(partial(f, self))
    def remove(self): self.hook.remove()
    def __del__(self): self.remove()

class Hooks(ListContainer):

    def __init__(self, ms, f): super().__init__([Hook(m,f) for m in ms])
    def __enter__(self, *args): return self
    def __exit__(self, *args): self.remove()
    def __del__(self): self.remove()

    def __delitem__(self,i):
        self[i].remove()
        super().__delitem__(i)

    def remove(self):
        for h in self: h.remove()

from torch.nn import init

def get_cnn_layers(data, nfs, layer, **kwargs):
    nfs = [1] + nfs
    return [layer(nfs[i], nfs[i+1], 5 if i==0 else 3, **kwargs)
            for i in range(len(nfs)-1)] + [
        nn.AdaptiveAvgPool2d(1), Lambda(flatten), nn.Linear(nfs[-1], data.c_out)]

def conv_layer(ni, nf, ks=3, stride=2, **kwargs):
    return nn.Sequential(
        nn.Conv2d(ni, nf, ks, padding=ks//2, stride=stride), GeneralRelu(**kwargs))

class GeneralRelu(nn.Module):
    def __init__(self, leak=None, sub=None, maxv=None):
        super().__init__()
        self.leak,self.sub,self.maxv = leak,sub,maxv

    def forward(self, x):
        x = F.leaky_relu(x,self.leak) if self.leak is not None else F.relu(x)
        if self.sub is not None: x.sub_(self.sub)
        if self.maxv is not None: x.clamp_max_(self.maxv)
        return x

def init_cnn(m, uniform=False):
    f = init.kaiming_uniform_ if uniform else init.kaiming_normal_
    for l in m:
        if isinstance(l, nn.Sequential):
            f(l[0].weight, a=0.1)
            l[0].bias.data.zero_()

def get_cnn_model(data, nfs, layer, **kwargs):
    return nn.Sequential(*get_cnn_layers(data, nfs, layer, **kwargs))

def append_stats(hook, mod, inp, outp):
    if not hasattr(hook,'stats'): hook.stats = ([],[],[])
    means,stds,hists = hook.stats
    if mod.training:
        means.append(outp.data.mean().cpu())
        stds .append(outp.data.std().cpu())
        hists.append(outp.data.cpu().histc(40,-7,7))