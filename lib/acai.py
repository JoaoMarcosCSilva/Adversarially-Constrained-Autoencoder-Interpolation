import tensorflow as tf
from tensorflow import keras
import numpy as np

from lib import baseline, mixup

class Autoencoder(baseline.Autoencoder):
    def __init__(self, Encoder, Decoder, Discriminator, Lambda, Gamma, Theta = 1.0, Autoencoder_Optimizer = None, Discriminator_Optimizer = None, Mixup = mixup.interpolate):
        super().__init__(Encoder, Decoder, Discriminator, Autoencoder_Optimizer, Discriminator_Optimizer)
        self.Lambda = Lambda
        self.Gamma = Gamma
        self.Theta = Theta
        self.Mixup = Mixup

    def interpolate_batch(self, batch):
        length = tf.shape(batch)[0]
        t = tf.random.uniform((length,1,1,1), 0, 0.5)
        code1 = self.Encoder(batch)
        code2 = code1[::-1]
        codeI = self.Mixup(code1, code2, t)
        result = self.Decoder(codeI)
        return result, tf.reshape(t*2, (-1,1))

    @tf.function
    def autoencoder_train_step(self, batch):
        with tf.GradientTape() as tape:
            x_true = batch
            x_pred = self.Autoencoder(batch)
            
            loss_reconstruction = self.autoencoder_loss(batch, x_pred) 

            mixbatch, t = self.interpolate_batch(batch)
            disc_pred = self.Discriminator(mixbatch)
            loss_discrimination = tf.reduce_mean(tf.square(disc_pred))

            loss = loss_reconstruction + self.Lambda*loss_discrimination
            
        gradients = tape.gradient(loss, self.Autoencoder.trainable_variables)
        self.Autoencoder_Optimizer.apply_gradients(zip(gradients, self.Autoencoder.trainable_variables))
        return loss, gradients, loss_reconstruction, loss_discrimination

    @tf.function
    def discriminator_train_step(self, batch):
        with tf.GradientTape() as tape:
            mixbatch, t = self.interpolate_batch(batch)
            pred_batch = self.Autoencoder(batch)

            disc_pred_real = self.Discriminator(mixup.interpolate(batch, pred_batch, self.Gamma))
            disc_pred_fake = self.Discriminator(mixbatch)
            
            loss_real = tf.reduce_mean(keras.losses.mse(tf.zeros(tf.shape(disc_pred_real)), disc_pred_real))
            loss_fake = tf.reduce_mean(keras.losses.mse(t, disc_pred_fake))

            loss = self.Theta*loss_real + loss_fake
        gradients = tape.gradient(loss, self.Discriminator.trainable_variables)
        self.Discriminator_Optimizer.apply_gradients(zip(gradients, self.Discriminator.trainable_variables))
        return loss, gradients, loss_real, loss_fake
    
    def train(self, epochs, dataset, verbose = 1, log_wandb = 0, plot_data = None, disc_steps = 1, ae_steps = 1):
        for epoch in range(epochs):
            if verbose:
                print('Epoch:',epoch+1)
                progress_bar = self.get_progress_bar(dataset, disc_steps + ae_steps)
            for step, batch in enumerate(dataset):
                if step % (disc_steps + ae_steps) == 0:
                    loss_disc, gradients_disc, loss_real_disc, loss_fake_disc = 0, 0, 0, 0
                    loss_ae, gradients_ae, loss_reconstruction_ae, loss_discrimination_ae = 0, 0, 0, 0
                if step % (disc_steps + ae_steps) < disc_steps:
                    loss_, gradients_, loss_real_, loss_fake_ = self.discriminator_train_step(batch)
                    loss_disc += loss_.numpy()
                    gradients_disc += np.mean([np.mean(i.numpy()) for i in gradients_])
                    loss_real_disc += loss_real_.numpy()
                    loss_fake_disc += loss_fake_.numpy()
                else:
                    loss_, gradients_, loss_reconstruction_, loss_discrimination_ = self.autoencoder_train_step(batch)
                    loss_ae += loss_.numpy()
                    gradients_ae += np.mean([np.mean(i.numpy()) for i in gradients_])
                    loss_reconstruction_ae += loss_reconstruction_.numpy()
                    loss_discrimination_ae += loss_discrimination_.numpy()
                if (step + 1) % (disc_steps + ae_steps) == 0:
                    metrics_dict = {'Autoencoder Loss': loss_ae / ae_steps, 
                            'Autoencoder Mean Gradient': gradients_ae / ae_steps,
                            'Autoencoder Reconstruction Loss': loss_reconstruction_ae / ae_steps,
                            'Autoencoder Discrimination Loss': loss_discrimination_ae / ae_steps,
                            'Discriminator Loss': loss_disc / disc_steps, 
                            'Discriminator Mean Gradient': gradients_disc / disc_steps,
                            'Discriminator Real Loss': loss_real_disc / disc_steps,
                            'Discriminator Fake Loss': loss_fake_disc / disc_steps}
                    
                    if log_wandb:
                        self.wandb_step(metrics_dict, epoch, plot = plot_data is not None, plot_data = plot_data)

                    if verbose == 1:
                        self.progress_bar_step(progress_bar, step//(disc_steps + ae_steps), metrics_dict, ['Autoencoder Loss','Discriminator Loss', 'Autoencoder Reconstruction Loss'])
                    if verbose == 2:
                        self.progress_bar_step(progress_bar, step//(disc_steps + ae_steps), metrics_dict)
                