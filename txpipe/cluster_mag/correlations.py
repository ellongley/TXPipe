import numpy as np
from ..base_stage import PipelineStage
from ..data_types import HDFFile, TextFile, SACCFile, PNGFile
import re
import time
import traceback

class CMPatches(PipelineStage):
    """

    This is currently copied from the in-progress treecorr-mpi branch.
    Think later how to
    """

    name = "CMPatches"
    inputs = [("cluster_mag_randoms", HDFFile)]
    outputs = [("cluster_mag_patches", TextFile)]
    config_options = {
        "npatch": 32,
        "every_nth": 100,
    }

    def run(self):
        import treecorr

        input_filename = self.get_input("cluster_mag_randoms")
        output_filename = self.get_output("cluster_mag_patches")

        # Build config info
        npatch = self.config["npatch"]
        every_nth = self.config["every_nth"]
        config = {
            "ext": "randoms",
            "ra_col": "ra",
            "dec_col": "dec",
            "ra_units": "degree",
            "dec_units": "degree",
            "every_nth": every_nth,
            "npatch": npatch,
        }

        # Create the catalog
        cat = treecorr.Catalog(input_filename, config)

        # Generate and write the output patch centres
        print(f"generating {npatch} centers")
        cat.write_patch_centers(output_filename)




class CMCorrelations(PipelineStage):
    name = "CMCorrelations"
    inputs = [
        ("cluster_mag_halo_tomography", HDFFile),
        ("cluster_mag_background", HDFFile),
        ("cluster_mag_patches", TextFile),
        ("cluster_mag_randoms", HDFFile),
    ]
    outputs = [("cluster_mag_correlations", SACCFile),]
    config_options = {
        "min_sep": 0.5,
        "max_sep": 300.0,
        "nbins": 9,
        "bin_slop": 0.1,
        "sep_units": "arcmin",
        "cores_per_task": 32,
        "verbose": 1,
        "var_method": "jackknife",
    }

    def run(self):
        import treecorr
        import sacc

        #  the names of the input files we will need
        background_file = self.get_input("cluster_mag_background")
        randoms_file = self.get_input("cluster_mag_randoms")
        patch_centers = self.get_input("cluster_mag_patches")


        treecorr_config = {
            x: y
            for x, y in self.config.items()
            if x in treecorr.NNCorrelation._valid_params
        }

        with self.open_input("cluster_mag_halo_tomography") as f:
            metadata = dict(f['tomography'].attrs)
            halo_bins = []
            for key, value in metadata.items():
                if re.match('bin_[0-9]', key):
                    halo_bins.append(value)
        print("Using halo bins: ", halo_bins)


        with self.open_input("cluster_mag_background") as f:
            sz = f['sample/ra'].size
            print(f"Background catalog size: {sz}")

        with self.open_input("cluster_mag_randoms") as f:
            sz = f['randoms/ra'].size
            print(f"Random catalog size: {sz}")



        # create background catalog
        bg_cat = treecorr.Catalog(
            background_file,
            self.config,
            patch_centers=patch_centers,
            ext="sample",
            ra_col="ra",
            dec_col="dec",
            ra_units="degrees",
            dec_units="degrees",
        )

        #  randoms catalog.  For now we use a single randoms file for both catalogs, but may want to change this.
        ran_cat = treecorr.Catalog(
            randoms_file,
            self.config,
            patch_centers=patch_centers,
            ext="randoms",
            ra_col="ra",
            dec_col="dec",
            ra_units="degrees",
            dec_units="degrees",
        )




        S = sacc.Sacc()
        S.add_tracer('misc', 'background')
        for halo_bin in halo_bins:
            S.add_tracer('misc', f'halo_{halo_bin}')

        t = time.time()
        print("Computing randoms x randoms")
        random_random = self.measure(ran_cat, ran_cat, treecorr_config)
        t1 = time.time()
        print(f"took {t1 - t:.1f} seconds")

        t = time.time()
        print("Computing random x background")
        random_bg = self.measure(ran_cat, bg_cat, treecorr_config)
        t1 = time.time()
        print(f"took {t1 - t:.1f} seconds")


        print("Computing background x background")
        t = time.time()
        bg_bg = self.measure(bg_cat, bg_cat, treecorr_config)
        t1 = time.time()
        print(f"took {t1 - t:.1f} seconds")

        bg_bg.calculateXi(random_random, random_bg)

        self.add_sacc_data(S, 'background', 'background', "galaxy_density_xi", bg_bg)

        comb = [bg_bg]

        for halo_bin in halo_bins:
            print(f"Computing with halo bin {halo_bin}")
            tracer1 = f'halo_{halo_bin}'
            tracer2 = f'background'
            try:
                halo_halo, halo_bg, meta = self.measure_halo_bin(bg_cat, ran_cat, halo_bin, random_random, random_bg, treecorr_config)
            except:
                traceback.print_exc()
                print(f"FAILED to calculate bin {halo_bin}.  Error above.  Continuing.")
                continue
            # We build up the comb list to get the covariance of it later
            # in the same order as our data points
            comb.append(halo_halo)
            comb.append(halo_bg)

            self.add_sacc_data(S, tracer1, tracer1, "halo_halo_density_xi", halo_halo, **meta)
            self.add_sacc_data(S, tracer1, tracer2, "halo_galaxy_density_xi", halo_bg, **meta)


        cov = treecorr.estimate_multi_cov(comb, self.config['var_method'])

        S.add_covariance(cov)
        S.metadata['nm'] = metadata['nm']
        S.metadata['nz'] = metadata['nz']


        S.save_fits(self.get_output("cluster_mag_correlations"))


    def add_sacc_data(self, S, tracer1, tracer2, corr_type, corr, **tags):
        theta = np.exp(corr.meanlogr)
        npair = corr.npairs
        weight = corr.weight

        xi = corr.xi
        err = np.sqrt(corr.varxi)
        n = len(xi)
        for i in range(n):
            S.add_data_point(corr_type, (tracer1, tracer2), xi[i],
                theta=theta[i], error=err[i], weight=weight[i], **tags)


    def measure_halo_bin(self, bg_cat, ran_cat, halo_bin, random_random, random_bg, treecorr_config):
        import treecorr
        halo_tomo_file = self.get_input("cluster_mag_halo_tomography")
        patch_centers = self.get_input("cluster_mag_patches")


        with self.open_input("cluster_mag_halo_tomography") as f:
            sz = f[f'tomography/bin_{halo_bin}/ra'].size
            metadata = dict(f[f'tomography/bin_{halo_bin}'].attrs)
            print(f"Halo bin {halo_bin} catalog size: {sz}")
            print("Metadata: ", metadata)

        # create foreground catalog using a specific foreground bin
        halo_cat = treecorr.Catalog(
            halo_tomo_file,
            self.config,
            patch_centers=patch_centers,
            ext=f"tomography/bin_{halo_bin}",
            ra_col="ra",
            dec_col="dec",
            ra_units="degrees",
            dec_units="degrees",
        )

        t = time.time()
        print(f"Computing {halo_bin} x {halo_bin}")
        halo_halo = self.measure(halo_cat, None, treecorr_config)

        print(f"Computing {halo_bin} x randoms")
        halo_random = self.measure(halo_cat, ran_cat, treecorr_config)

        print(f"Computing {halo_bin} x background")
        halo_bg = self.measure(halo_cat, bg_cat, treecorr_config)
        t = time.time() - t
        print(f"Bin {halo_bin} took {t:.1f} seconds")

        # Use these combinations to calculate the correlations functions
        halo_halo.calculateXi(random_random, halo_random)
        halo_bg.calculateXi(random_random, halo_random, random_bg)

        return halo_halo, halo_bg, metadata


    def measure(self, cat1, cat2, treecorr_config):
        import treecorr
        # Get any treecorr-related params from our config, while leaving out any that are intended
        # for this code

        p = treecorr.NNCorrelation(**treecorr_config)
        p.process(cat1, cat2, low_mem=False)
        return p



class CMCorrelationsPlot(PipelineStage):
    name = "CMCorrelationsPlot"
    inputs = [("cluster_mag_correlations", SACCFile),]
    outputs = [
        ("cluster_mag_halo_halo_plot", PNGFile),
        ("cluster_mag_halo_bg_plot", PNGFile)

    ]
    config_options = {}
    def run(self):
        import sacc
        import matplotlib
        matplotlib.use('agg')
        import matplotlib.pyplot as plt
        S = sacc.Sacc.load_fits(self.get_input("cluster_mag_correlations"))

        nm = S.metadata['nm']
        nz = S.metadata['nz']

        self.halo_halo_plot(S, nm, nz)
        self.halo_bg_plot(S, nm, nz)



    def halo_halo_plot(self, S, nm, nz):
        import matplotlib.pyplot as plt

        f = self.open_output('cluster_mag_halo_halo_plot', wrapper=True, figsize=(nm*5,nz*5))
        fig = f.file
        axes = fig.subplots(nm, nz, sharex='col', sharey=False, squeeze=False)
        for i in range(nz):
            for j in range(nm):
                ax = axes[i, j]
                tracer = f'halo_{i}_{j}'
                theta = S.get_tag('theta', 'halo_halo_density_xi', (tracer, tracer))
                error = S.get_tag('error', 'halo_halo_density_xi', (tracer, tracer))
                mmin = S.get_tag('mass_min', 'halo_halo_density_xi', (tracer, tracer))[0] / 1e13
                mmax = S.get_tag('mass_max', 'halo_halo_density_xi', (tracer, tracer))[0] / 1e13
                zmin = S.get_tag('z_min', 'halo_halo_density_xi', (tracer, tracer))[0]
                zmax = S.get_tag('z_max', 'halo_halo_density_xi', (tracer, tracer))[0]
                if not len(theta):
                    continue
                xi = S.get_mean('halo_halo_density_xi', (tracer, tracer))

                ax.errorbar(theta, xi, error, fmt='r.')
                ax.set_xscale('log')
                ax.axhline(0, color='k')
                ax.text(0.5, 0.9, f'z = {zmin:.2f} -- {zmax:.2f}\nM = ({mmin:.2f} -- {mmax:.2f}) $\\times 10^{13}$', transform=ax.transAxes)

                ax.set_title(f"Halo bin {i} {j}")

                # Add axis labels for the edge plots
                if j == 0:
                    ax.set_ylabel("xi")
                if i == nm - 1:
                    ax.set_xlabel("theta")
        plt.suptitle("Halo-Halo Autocorrelations")
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        f.close()

    def halo_bg_plot(self, S, nm, nz):
        import matplotlib.pyplot as plt

        f = self.open_output('cluster_mag_halo_bg_plot', wrapper=True, figsize=(nm*5,nz*5))
        fig = f.file
        axes = fig.subplots(nm, nz, sharex='col', sharey=False, squeeze=False)
        for i in range(nz):
            for j in range(nm):
                ax = axes[i, j]
                tracer = f'halo_{i}_{j}'
                theta = S.get_tag('theta', 'halo_galaxy_density_xi', (tracer, 'background'))
                error = S.get_tag('error', 'halo_galaxy_density_xi', (tracer, 'background'))
                mmin = S.get_tag('mass_min', 'halo_halo_density_xi', (tracer, tracer))[0] / 1e13
                mmax = S.get_tag('mass_max', 'halo_halo_density_xi', (tracer, tracer))[0] / 1e13
                zmin = S.get_tag('z_min', 'halo_halo_density_xi', (tracer, tracer))[0]
                zmax = S.get_tag('z_max', 'halo_halo_density_xi', (tracer, tracer))[0]
                if not len(theta):
                    continue
                xi = S.get_mean('halo_galaxy_density_xi', (tracer, 'background'))

                ax.errorbar(theta, xi, error, fmt='r.')
                ax.set_xscale('log')
                ax.axhline(0, color='k')
                ax.text(0.5, 0.9, f'z = {zmin:.2f} -- {zmax:.2f}\nM = ({mmin:.2f} -- {mmax:.2f}) $\\times 10^{{13}}$', transform=ax.transAxes)

                ax.set_title(f"Halo bin {i} {j}")
                if j == 0:
                    ax.set_ylabel("xi")
                if i == nm - 1:
                    ax.set_xlabel("theta")
        plt.suptitle("Halo-Background Correlations")
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        f.close()

