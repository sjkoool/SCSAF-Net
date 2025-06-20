import torch
import torch.nn as nn
import torch.nn.functional as F
from pdb import set_trace as stx
import numbers
from einops import rearrange
from torchvision.transforms import GaussianBlur

class BaseNetwork(nn.Module):
    def __init__(self):
        super(BaseNetwork, self).__init__()

    def init_weights(self, init_type='normal', gain=0.02):
        def init_func(m):
            classname = m.__class__.__name__
            if hasattr(m, 'weight') and (classname.find('Conv') != -1 or classname.find('Linear') != -1):
                if init_type == 'normal':
                    nn.init.normal_(m.weight.data, 0.0, gain)
                elif init_type == 'xavier':
                    nn.init.xavier_normal_(m.weight.data, gain=gain)
                elif init_type == 'kaiming':
                    nn.init.kaiming_normal_(m.weight.data, a=0, mode='fan_in')
                elif init_type == 'orthogonal':
                    nn.init.orthogonal_(m.weight.data, gain=gain)

                if hasattr(m, 'bias') and m.bias is not None:
                    nn.init.constant_(m.bias.data, 0.0)

            elif classname.find('BatchNorm2d') != -1:
                nn.init.normal_(m.weight.data, 1.0, gain)
                nn.init.constant_(m.bias.data, 0.0)

        self.apply(init_func)


def spectral_norm(module, mode=True):
    if mode:
        return nn.utils.spectral_norm(module)

    return module


class Discriminator(BaseNetwork):
    def __init__(self, in_channels, use_sigmoid=True, use_spectral_norm=True, init_weights=True):
        super(Discriminator, self).__init__()
        self.use_sigmoid = use_sigmoid

        self.conv1 = self.features = nn.Sequential(
            spectral_norm(nn.Conv2d(in_channels=in_channels, out_channels=64, kernel_size=4, stride=2, padding=1,
                                    bias=not use_spectral_norm), use_spectral_norm),
            nn.LeakyReLU(0.2, inplace=True),
        )

        self.conv2 = nn.Sequential(
            spectral_norm(nn.Conv2d(in_channels=64, out_channels=128, kernel_size=4, stride=2, padding=1,
                                    bias=not use_spectral_norm), use_spectral_norm),
            nn.LeakyReLU(0.2, inplace=True),
        )

        self.conv3 = nn.Sequential(
            spectral_norm(nn.Conv2d(in_channels=128, out_channels=256, kernel_size=4, stride=2, padding=1,
                                    bias=not use_spectral_norm), use_spectral_norm),
            nn.LeakyReLU(0.2, inplace=True),
        )

        self.conv4 = nn.Sequential(
            spectral_norm(nn.Conv2d(in_channels=256, out_channels=512, kernel_size=4, stride=1, padding=1,
                                    bias=not use_spectral_norm), use_spectral_norm),
            nn.LeakyReLU(0.2, inplace=True),
        )

        self.conv5 = nn.Sequential(
            spectral_norm(nn.Conv2d(in_channels=512, out_channels=1, kernel_size=4, stride=1, padding=1,
                                    bias=not use_spectral_norm), use_spectral_norm),
        )

        if init_weights:
            self.init_weights()

    def forward(self, x):
        conv1 = self.conv1(x)
        conv2 = self.conv2(conv1)
        conv3 = self.conv3(conv2)
        conv4 = self.conv4(conv3)
        conv5 = self.conv5(conv4)

        outputs = conv5
        if self.use_sigmoid:
            outputs = torch.sigmoid(conv5)

        return outputs, [conv1, conv2, conv3, conv4, conv5]



def to_3d(x):
    return rearrange(x, 'b c h w -> b (h w) c')


def to_4d(x, h, w):
    return rearrange(x, 'b (h w) c -> b c h w', h=h, w=w)


class BiasFree_LayerNorm(nn.Module):
    def __init__(self, normalized_shape):
        super(BiasFree_LayerNorm, self).__init__()
        if isinstance(normalized_shape, numbers.Integral):
            normalized_shape = (normalized_shape,)
        normalized_shape = torch.Size(normalized_shape)

        assert len(normalized_shape) == 1

        self.weight = nn.Parameter(torch.ones(normalized_shape))
        self.normalized_shape = normalized_shape

    def forward(self, x):
        sigma = x.var(-1, keepdim=True, unbiased=False)
        return x / torch.sqrt(sigma + 1e-5) * self.weight


class WithBias_LayerNorm(nn.Module):
    def __init__(self, normalized_shape):
        super(WithBias_LayerNorm, self).__init__()
        if isinstance(normalized_shape, numbers.Integral):
            normalized_shape = (normalized_shape,)
        normalized_shape = torch.Size(normalized_shape)

        assert len(normalized_shape) == 1

        self.weight = nn.Parameter(torch.ones(normalized_shape))
        self.bias = nn.Parameter(torch.zeros(normalized_shape))
        self.normalized_shape = normalized_shape

    def forward(self, x):
        mu = x.mean(-1, keepdim=True)
        sigma = x.var(-1, keepdim=True, unbiased=False)
        return (x - mu) / torch.sqrt(sigma + 1e-5) * self.weight + self.bias


class LayerNorm(nn.Module):
    def __init__(self, dim, LayerNorm_type):
        super(LayerNorm, self).__init__()
        if LayerNorm_type == 'BiasFree':
            self.body = BiasFree_LayerNorm(dim)
        else:
            self.body = WithBias_LayerNorm(dim)

    def forward(self, x):
        h, w = x.shape[-2:]
        return to_4d(self.body(to_3d(x)), h, w)



class FeedForward(nn.Module):
    def __init__(self, dim, ffn_expansion_factor, bias):
        super(FeedForward, self).__init__()
        hidden_features = int(dim * ffn_expansion_factor)
        self.project_in = nn.Conv2d(dim, hidden_features * 2, kernel_size=1, bias=bias)
        self.dwconv = nn.Conv2d(hidden_features * 2, hidden_features * 2, kernel_size=3, stride=1, padding=1,
                                groups=hidden_features * 2, bias=bias)
        self.project_out = nn.Conv2d(hidden_features, dim, kernel_size=1, bias=bias)

    def forward(self, x):
        x = self.project_in(x)

        x1, x2 = self.dwconv(x).chunk(2, dim=1)

        x = F.gelu(x1) * x2
        x = self.project_out(x)
        return x



class SCSA(nn.Module):
    def __init__(self, in_channels, rate=4, num_heads=4, window_size=8):
        super(SCSA, self).__init__()
        self.num_heads = num_heads
        self.head_dim = in_channels // num_heads
        self.scale = self.head_dim ** -0.5
        self.window_size = window_size
        assert in_channels % num_heads == 0, "in_channels must be divisible by num_heads"
        self.qkv_proj = nn.Linear(in_channels, in_channels * 3)
        self.out_proj = nn.Linear(in_channels, in_channels)
        self.channel_attention = nn.Sequential(
            nn.Linear(in_channels, in_channels // rate),
            nn.ReLU(inplace=True),
            nn.Linear(in_channels // rate, in_channels)
        )
        self.spatial_attention = nn.Sequential(
            nn.Conv2d(in_channels, in_channels // rate, kernel_size=7, padding=3, groups=in_channels // rate),
            nn.BatchNorm2d(in_channels // rate),
            nn.ReLU(inplace=True),
            nn.Conv2d(in_channels // rate, in_channels, kernel_size=7, padding=3, groups=in_channels // rate),
            nn.BatchNorm2d(in_channels)
        )
    def channel_attention_forward(self, x):

        b, c, h, w = x.shape
        x_permute = x.permute(0, 2, 3, 1).reshape(b, -1, c)  # (b, h*w, c)
        x_att_permute = self.channel_attention(x_permute).view(b, h, w, c)  # (b, h, w, c)
        x_channel_att = x_att_permute.permute(0, 3, 1, 2).sigmoid()  # (b, c, h, w)
        return x * x_channel_att  #
    def channel_shuffle(self, x, groups=4):

        batchsize, num_channels, height, width = x.size()
        channels_per_group = num_channels // groups
        x = x.view(batchsize, groups, channels_per_group, height, width)
        x = torch.transpose(x, 1, 2).contiguous()
        x = x.view(batchsize, -1, height, width)
        return x

    def qkv_attention(self, x):

        b, c, h, w = x.shape
        wh, ww = self.window_size, self.window_size

        assert h % wh == 0 and w % ww == 0, "Feature map size must be divisible by window size."
        #1. Split Window
        x = x.view(b, c, h // wh, wh, w // ww, ww)  # (b, c, H/wh, wh, W/ww, ww)
        x = x.permute(0, 2, 4, 3, 5, 1).contiguous().view(-1, wh * ww, c)  # (num_windows * b, wh*ww, c)
        # 2. Calculating QKV
        qkv = self.qkv_proj(x)  # (num_windows * b, wh*ww, c*3)
        q, k, v = torch.chunk(qkv, 3, dim=-1)
        # 3. Head segmentation
        q = q.view(-1, wh * ww, self.num_heads, self.head_dim).permute(0, 2, 1, 3)
        k = k.view(-1, wh * ww, self.num_heads, self.head_dim).permute(0, 2, 1, 3)
        v = v.view(-1, wh * ww, self.num_heads, self.head_dim).permute(0, 2, 1, 3)
        #4. Computing window attention
        attn = (q @ k.transpose(-2, -1)) * self.scale
        attn = attn.softmax(dim=-1)
        out = (attn @ v).permute(0, 2, 1, 3).reshape(-1, wh * ww, c)
        out = self.out_proj(out)
        #5. Restore Window
        out = out.view(b, h // wh, w // ww, wh, ww, c).permute(0, 5, 1, 3, 2, 4)
        out = out.contiguous().view(b, c, h, w)
        return out
    def forward(self, x):
        # First perform channel attention
        x = self.channel_attention_forward(x)
        #Perform QKV calculation (window attention)
        x_qkv = self.qkv_attention(x)
        x = x + x_qkv  # Residual Connection
        #Perform channel shuffle
        x = self.channel_shuffle(x, groups=4)
        #Perform spatial attention
        x_spatial_att = self.spatial_attention(x).sigmoid()
        #Final Output
        return x * x_spatial_att





class Oreo(nn.Module):
    def __init__(self, dim, num_heads, ffn_expansion_factor, bias, LayerNorm_type):
        super(Oreo, self).__init__()

        self.norm1_1 = LayerNorm(dim, LayerNorm_type)
        self.ffn1 = FeedForward(dim, ffn_expansion_factor, bias)

        self.norm1 = LayerNorm(dim, LayerNorm_type)

        # self.attn = Attention(dim, num_heads, bias)
        self.attn = Oreo(dim)

        self.norm2 = LayerNorm(dim, LayerNorm_type)

        self.ffn = FeedForward(dim, ffn_expansion_factor, bias)

    def forward(self, x):
        x = x + self.ffn1(self.norm1_1(x))
        x = x + self.attn(self.norm1(x))
        x = x + self.ffn(self.norm2(x))

        return x


##########################################################################
## Gated Embedding layer
class GatedEmb(nn.Module):
    def __init__(self, in_c=4, dim=48, bias=False):
        # 原来的def __init__(self, in_c=3, embed_dim=48, bias=False):
        super(GatedEmb, self).__init__()
        self.gproj1 = nn.Conv2d(in_c, dim * 2, kernel_size=3, stride=1, padding=1, bias=bias)

    def forward(self, x):
        # x = self.proj(x)
        x = self.gproj1(x)
        x1, x2 = x.chunk(2, dim=1)
        x = F.gelu(x1) * x2

        return x


class Downsample(nn.Module):
    def __init__(self, n_feat):
        super(Downsample, self).__init__()

        self.body = nn.Sequential(nn.Conv2d(n_feat, n_feat // 2, kernel_size=3, stride=1, padding=1, bias=False),
                                  nn.PixelUnshuffle(2))

        self.body2 = nn.Sequential(nn.PixelUnshuffle(2))

        self.proj = nn.Conv2d(n_feat * 4, n_feat * 2, kernel_size=3, stride=1, padding=1, groups=n_feat * 2, bias=False)

    def forward(self, x, mask):

        out = self.body(x)
        out_mask = self.body2(mask)
        b, n, h, w = out.shape
        t = torch.zeros((b, 2 * n, h, w)).cuda()
        for i in range(n):
            t[:, 2 * i, :, :] = out[:, i, :, :]
        for i in range(n):
            if i <= 3:
                t[:, 2 * i + 1, :, :] = out_mask[:, i, :, :]
            else:
                t[:, 2 * i + 1, :, :] = out_mask[:, (i % 4), :, :]

        return self.proj(t)



class LaplacianFilter(nn.Module):
    def __init__(self):
        super(LaplacianFilter, self).__init__()
        self.kernel = torch.tensor([[1, -2, 1],
                                    [-2, 4, -2],
                                    [1, -2, 1]], dtype=torch.float32).unsqueeze(0).unsqueeze(0)
        self.kernel = nn.Parameter(self.kernel, requires_grad=False)

    def forward(self, x):
        B, C, H, W = x.shape
        x = x.view(B * C, 1, H, W)  # 将每个通道分开处理
        filtered = F.conv2d(x, self.kernel, padding=1)
        return filtered.view(B, C, H, W)  # 重塑回原始形状


# Gaussian blur (extract low frequency)
class GaussianBlurLayer(nn.Module):
    def __init__(self, kernel_size=5, sigma=2.0):
        super(GaussianBlurLayer, self).__init__()
        self.blur = GaussianBlur(kernel_size, sigma=sigma)

    def forward(self, x):
        return self.blur(x)


# Edge enhancement module (high frequency processing)
class EdgeEnhancementModule(nn.Module):
    def __init__(self, in_channels, out_channels):
        super(EdgeEnhancementModule, self).__init__()

        # 增加通道数的卷积层
        self.conv1 = nn.Conv2d(in_channels, 64, kernel_size=3, padding=1)  # From the number of input channels to 64
        self.conv2 = nn.Conv2d(64, 128, kernel_size=3, padding=1)          # From 64 to 128
        self.conv3 = nn.Conv2d(128, 256, kernel_size=3, padding=1)         # From 128 to 256
        self.conv4 = nn.Conv2d(256, out_channels, kernel_size=3, padding=1) # From 256 to the number of output channels
        self.relu = nn.ReLU()

    def forward(self, x):
        # Apply ReLU activation function after each convolution operation
        x = self.relu(self.conv1(x))
        x = self.relu(self.conv2(x))
        x = self.relu(self.conv3(x))
        x = self.conv4(x)             # The last layer of convolution, without activation (optional depending on the task)
        return x


# Main upsampling module, integrating high and low frequency extraction and enhancement
class Upsample(nn.Module):
    def __init__(self, n_feat):
        super(Upsample, self).__init__()

        # 上采样模块
        self.body = nn.Sequential(
            nn.Conv2d(n_feat, n_feat * 2, kernel_size=3, stride=1, padding=1, bias=False),
            nn.PixelShuffle(2)
        )

        # Separation of high and low frequencies (combining FFT and spatial domain methods)
        self.laplacian = LaplacianFilter()  # High frequency extraction (spatial domain)
        self.gaussian_blur = GaussianBlurLayer(kernel_size=5, sigma=2.0)  # Low frequency extraction (spatial domain)

        # High and low frequency convolution module
        self.high_freq_conv = nn.Conv2d(n_feat // 2, n_feat // 2, kernel_size=3, stride=1, padding=1, bias=False)
        self.low_freq_conv = nn.Conv2d(n_feat // 2, n_feat // 2, kernel_size=3, stride=1, padding=1, bias=False)

        # High frequency enhancement module (combined with high frequency FFT processing)
        self.edge_enhance = EdgeEnhancementModule(n_feat // 2, n_feat // 2)

        # Dynamic Weights


        self.weight_high = nn.Parameter(torch.tensor([[0.7]]))  # Initialize to 0.7
        self.weight_low = nn.Parameter(torch.tensor([[0.3]]))

    def forward(self, x, mask=None):

        x = self.body(x)

        # Separation of high and low frequencies (combining FFT and spatial domain methods)
        x_freq = torch.fft.fft2(x.to(x.device))
        x_freq_shifted = torch.fft.fftshift(x_freq)

        B, C, H, W = x.shape
        y, x_coords = torch.meshgrid(torch.arange(H, device=x.device), torch.arange(W, device=x.device), indexing='ij')
        dist = ((y - H // 2) ** 2 + (x_coords - W // 2) ** 2).sqrt()

        high_freq_mask = (dist > H // 4).float().unsqueeze(0).unsqueeze(0)
        low_freq_mask = 1 - high_freq_mask

        high_freq_fft = high_freq_mask * x_freq_shifted
        low_freq_fft = low_freq_mask * x_freq_shifted

        x_high_fft = torch.real(torch.fft.ifft2(torch.fft.ifftshift(high_freq_fft)))
        x_low_fft = torch.real(torch.fft.ifft2(torch.fft.ifftshift(low_freq_fft)))

        # High frequency enhancement (combined with FFT and convolution processing)
        high_freq_space = self.laplacian(x)
        x_high = self.high_freq_conv(high_freq_space + x_high_fft)
        x_high = self.edge_enhance(x_high)

        # Low frequency part convolution
        low_freq_space = self.gaussian_blur(x)
        x_low = self.low_freq_conv(low_freq_space + x_low_fft)

        # Dynamic weight fusion of high and low frequency features
        weights = torch.softmax(torch.cat([self.weight_high, self.weight_low], dim=0), dim=0)
        x = weights[0] * x_high + weights[1] * x_low

        return x


class SCSAF(nn.Module):
    def __init__(self,
                 inp_channels=4,
                 out_channels=3,
                 dim=48,
                 num_blocks=[4, 6, 6, 8],

                 heads=[1, 2, 4, 8],
                 ffn_expansion_factor=2.66,
                 bias=False,
                 LayerNorm_type='WithBias',
                 ):
        super(SCSAF, self).__init__()


        self.patch_embed = GatedEmb(in_c=6, dim=dim)

        self.encoder_level1 = nn.Sequential(*[
            Oreo(dim=dim, num_heads=heads[0], ffn_expansion_factor=ffn_expansion_factor, bias=bias,
                          LayerNorm_type=LayerNorm_type) for i in range(num_blocks[0])])

        self.down1_2 = Downsample(dim)  ## From Level 1 to Level 2
        self.encoder_level2 = nn.Sequential(*[
            Oreo(dim=int(dim * 2 ** 1), num_heads=heads[1], ffn_expansion_factor=ffn_expansion_factor,
                          bias=bias, LayerNorm_type=LayerNorm_type) for i in range(num_blocks[1])])

        self.down2_3 = Downsample(int(dim * 2 ** 1))  ## From Level 2 to Level 3
        self.encoder_level3 = nn.Sequential(*[
            Oreo(dim=int(dim * 2 ** 2), num_heads=heads[2], ffn_expansion_factor=ffn_expansion_factor,
                          bias=bias, LayerNorm_type=LayerNorm_type) for i in range(num_blocks[2])])

        self.down3_4 = Downsample(int(dim * 2 ** 2))  ## From Level 3 to Level 4
        self.latent = nn.Sequential(*[
            Oreo(dim=int(dim * 2 ** 3), num_heads=heads[3], ffn_expansion_factor=ffn_expansion_factor,
                          bias=bias, LayerNorm_type=LayerNorm_type) for i in range(num_blocks[3])])

        self.up4_3 = Upsample(int(dim * 2 ** 3))  ## From Level 4 to Level 3
        self.reduce_chan_level3 = nn.Conv2d(int(dim * 2 ** 3), int(dim * 2 ** 2), kernel_size=1, bias=bias)
        self.decoder_level3 = nn.Sequential(*[
            Oreo(dim=int(dim * 2 ** 2), num_heads=heads[2], ffn_expansion_factor=ffn_expansion_factor,
                          bias=bias, LayerNorm_type=LayerNorm_type) for i in range(num_blocks[2])])

        self.up3_2 = Upsample(int(dim * 2 ** 2))  ## From Level 3 to Level 2
        self.reduce_chan_level2 = nn.Conv2d(int(dim * 2 ** 2), int(dim * 2 ** 1), kernel_size=1, bias=bias)
        self.decoder_level2 = nn.Sequential(*[
            Oreo(dim=int(dim * 2 ** 1), num_heads=heads[1], ffn_expansion_factor=ffn_expansion_factor,
                          bias=bias, LayerNorm_type=LayerNorm_type) for i in range(num_blocks[1])])

        self.up2_1 = Upsample(int(dim * 2 ** 1))  ## From Level 2 to Level 1  (NO 1x1 conv to reduce channels)

        self.decoder_level1 = nn.Sequential(*[
            Oreo(dim=int(dim * 2 ** 1), num_heads=heads[1], ffn_expansion_factor=ffn_expansion_factor,
                          bias=bias, LayerNorm_type=LayerNorm_type) for i in range(num_blocks[0])])

        self.output = nn.Sequential(
            nn.Conv2d(int(dim * 2 ** 1), out_channels, kernel_size=3, stride=1, padding=1, bias=bias)
            )

    def forward(self, inp_img, mask_whole, mask_half, mask_quarter, mask_tiny):
        
        inp_enc_level1 = self.patch_embed(torch.cat((inp_img, mask_whole), dim=1))

        out_enc_level1 = self.encoder_level1(inp_enc_level1)

        inp_enc_level2 = self.down1_2(out_enc_level1, mask_whole)
        out_enc_level2 = self.encoder_level2(inp_enc_level2)

        inp_enc_level3 = self.down2_3(out_enc_level2, mask_half)
        out_enc_level3 = self.encoder_level3(inp_enc_level3)

        inp_enc_level4 = self.down3_4(out_enc_level3, mask_quarter)

        latent = self.latent(inp_enc_level4)

        inp_dec_level3 = self.up4_3(latent, mask_tiny)
        inp_dec_level3 = torch.cat([inp_dec_level3, out_enc_level3], 1)

        inp_dec_level3 = self.reduce_chan_level3(inp_dec_level3)
        out_dec_level3 = self.decoder_level3(inp_dec_level3)

        inp_dec_level2 = self.up3_2(out_dec_level3, mask_quarter)
        inp_dec_level2 = torch.cat([inp_dec_level2, out_enc_level2], 1)

        inp_dec_level2 = self.reduce_chan_level2(inp_dec_level2)
        out_dec_level2 = self.decoder_level2(inp_dec_level2)

        inp_dec_level1 = self.up2_1(out_dec_level2, mask_half)
        inp_dec_level1 = torch.cat([inp_dec_level1, out_enc_level1], 1)

        out_dec_level1 = self.decoder_level1(inp_dec_level1)

        out_dec_level1 = self.output(out_dec_level1)

        out_dec_level1 = (torch.tanh(out_dec_level1) + 1) / 2
        return out_dec_level1






